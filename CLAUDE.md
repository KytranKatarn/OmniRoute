# A.R.C.H.I.E. Platform

**Version**: 5.33.0 | **Host**: 192.168.1.200 | **Status**: Operational

---

## ⛔ MANDATORY PRE-FLIGHT CHECKLIST

**Run this BEFORE writing any code. No exceptions.**

```
□ 1. SEARCH  — mcp search_knowledge for the topic. Search mistake_learned too.
□ 2. READ    — Read the existing code you're about to modify. Read the reference implementation.
□ 3. VERIFY  — Check CSS classes exist (grep). Check DB columns (schema). Check function signatures.
□ 4. PLAN    — If 3+ steps, enter plan mode. Get user approval before coding.
□ 5. TEST    — Can you test this? If NO, tell user upfront. Don't write untestable code.
```

**After EVERY code change:**
```
□ 1. BRANCH  — NEVER commit directly to main. Create a feature branch first.
□ 2. COMMIT  — Stage and commit the change to the feature branch
□ 3. DEPLOY  — docker compose restart archie_platform
□ 4. TEST    — Browser test (Playwright or manual). Show output.
□ 5. PR      — Push branch, create PR via `gh pr create`. Let user merge.
□ 6. CLAIM   — Only NOW say "done" — with proof
```

**Branch naming:**
```
feat/short-description    — new features
fix/short-description     — bug fixes
chore/short-description   — maintenance, docs, deps
auto/short-description    — AI/automation-initiated changes
```

**Direct push to main is ONLY allowed for:**
- Emergency hotfixes with explicit user approval
- Trivial one-line fixes (typos, version bumps) with user approval

**On failure:**
```
□ Attempt 1 fails → Understand WHY (read code, check logs, verify state)
□ Attempt 2 fails → STOP. Tell user what you tried and why it failed. Ask how to proceed.
□ NEVER spiral through 20 attempts. NEVER corrupt working code trying workarounds.
```

---

## Model Routing & Weekly Buckets (Max 20x)

Three independent weekly buckets reset Thursday. Route work deliberately.

| Bucket | Use for | How to invoke |
|---|---|---|
| **All models** (Opus + Sonnet + Haiku) | Hard reasoning, architecture, multi-file refactor, complex debugging | `/model opus` or `/fast` (Opus 4.6, faster output) |
| **Sonnet only** (safety-valve) | Routine work — reads, edits, commits, boot/stats/status skills, tool-chain execution | `/model sonnet` |
| **Claude Design** (separate quota, free with Max) | Visual mockups, prototypes, slides, LCARS layout exploration — Project #223 lives here | https://claude.ai/design |

**Default rule**: Sonnet for routine work. Opus only when reasoning is actually required. Claude Design for anything visual — it does not touch the Claude Code budget.

`/archie-boot`, `/archie-stats`, `/archie-save`, `/archie-status`, `/archie-search`, `/archie-project` are tool-chain execution — **run them on Sonnet**.

---

## 6 Rules (Memorize These)

| # | Rule | One-liner |
|---|------|-----------|
| 1 | **Verify Everything** | Never claim done without live browser proof |
| 2 | **Read Before Building** | Search KB + read existing code before writing anything |
| 3 | **Never Guess** | If you haven't read it, you don't know it. 2 strikes → ask user |
| 4 | **No Wasted Effort** | Can't test it? Say so. Beyond capability? Say so immediately |
| 5 | **Follow Patterns** | Departments→AgentService, modals→LCARS, LLM→Bridge, SaaS→per-user |
| 6 | **Platform Rules** | User is REMOTE (192.168.1.200). Never commit secrets. Bridge first |

Full details in memory files: `feedback_01` through `feedback_06`

---

## Session Start Protocol (MANDATORY)

Every new session MUST begin with one of:
- Run `/archie-boot` (preferred — guided session boot)
- Call `mcp__archie__session_briefing` with the task topic (one-call alternative)

**The knowledge base has 25,700+ entries with embeddings (99% coverage). Search before building. Search before asking.**
- `search_knowledge` — semantic + text search across all knowledge types
- `recall_context` — recall past context for a topic
- `search_knowledge` with types: ["mistake_learned"] — prevent repeating costly errors

**The user is REMOTE** — always use 192.168.1.200, never localhost.

---

## Quick Reference

| Resource | Location |
|----------|----------|
| Platform | http://192.168.1.200:3000 |
| Dev HQ | http://192.168.1.200:3000/tools/consciousness/#devhq (tab inside Consciousness) |
| Docs | `knowledge_base` table → Consciousness Knowledge tab or MCP `search_knowledge` |
| Modules | `/mnt/archie_brain/platform_v2/tools/` (36 modules) |
| MCP Tools | 87 tools via `.mcp.json` (incl. `session_briefing`, `propose_hire` #2124, `delegate_task` #2207) |
| Projects | `unified_projects` table → MCP `get_projects` / `create_task` |

## Architecture (3 Core Systems + 6 Subsystems)

### 3 Core Systems
1. **Autonomy Module** - Scheduled jobs, background processing (`ai_bridge/agent_loop.py`)
2. **Department HQ** - Agents, departments, dispatch, fleet, jobs — 12 tabs (`tools/department_hq/`)
3. **AI Bridge** - Model routing, embeddings, knowledge analysis (`ai_bridge/`)

### 6 Subsystems
4. **Knowledge Base** - `knowledge_base` table (~25,700 entries, 99% embedded, quality-scored)
5. **Module System** - Flask Blueprints in `/platform_v2/tools/` (36 modules)
6. **Consciousness** - Knowledge analytics, AI processing, embedding coverage
7. **Self-Healing Pipeline** - Audit → Propose → Fix → Verify (`services/audit_pipeline.py`)
8. **C.R.E.E.D.** - Ethics & compliance, standalone at :8086 + DHQ tab (Decision #438)
9. **Agent Service** - Centralized agent CRUD, lifecycle (`services/agent_service.py`)

*Starbase Command merged into Department HQ Fleet tab (2026-04-08). Dispatcher moved to DHQ services (Decision #440).*

## Source of Truth

| Data | Location | Access |
|------|----------|--------|
| Documentation & Knowledge | `knowledge_base` table | MCP `search_knowledge`, `store_memory` |
| Projects & Tasks | `unified_projects` + `unified_tasks` | MCP `get_projects`, `create_task`, `complete_task` |
| Decisions | `project_decisions` table | MCP `log_decision` |
| Module Code | `/platform_v2/tools/` | Direct file access |
| Roadmaps | `knowledge_base` vault_notes with "roadmap" tag | MCP `search_knowledge` |

**NO filesystem docs** — `/docs/` is archived. **NO TODO_LIST.md** — use `unified_tasks`. **NO ad-hoc memory** — use Dev HQ.

## Key Files

```
platform_v2/app.py                          - Flask app + |localtime filter
platform_v2/module_registry.py              - Module definitions
platform_v2/rbac.py                         - Permissions
platform_v2/database.py                     - DB connection
platform_v2/services/agent_service.py       - Centralized agent CRUD, lifecycle, skills, welfare (+propose_hire #2124)
platform_v2/services/agent_models.py        - Model load/unload/warmboot
platform_v2/services/agent_dispatch.py      - Candidate selection, scoring
platform_v2/services/audit_pipeline.py      - Self-healing repair pipeline
platform_v2/services/agent_social_service.py - Social presence
platform_v2/services/work_tracking_service.py - Work sessions, metrics
platform_v2/services/department_coordinator.py - Skill-first routing w/ cross-dept fallback (ADR-002, #2217)
platform_v2/services/delegation_service.py  - Claude → A.R.C.H.I.E. delegation surface (#276)
platform_v2/services/misroute_to_proposal_adapter.py - S.P.E.C.T.R.A. observer→proposal adapter (#2186)
platform_v2/tools/department_hq/            - Department management (6 tabs)
platform_v2/tools/agent_academy/            - Training & benchmarks (5 tabs)
platform_v2/static/js/archie-time.js        - Timezone formatter
ai_bridge/archie_bridge.py                  - AI routing (intent parse + cost calc)
ai_bridge/knowledge_analyzer.py             - Knowledge extraction
ai_bridge/embedding_service.py              - Vector embeddings
platform_v2/tools/department_hq/services/department_dispatcher.py - Dispatch entry point (renamed from bridge_dispatcher, Decision #441)
platform_v2/tools/department_hq/services/orchestration_engine.py - 8-step orchestration pipeline
platform_v2/tools/department_hq/services/smart_router.py         - GPU-aware 11-tier routing + CAPABILITY_TAXONOMY
platform_v2/tools/department_hq/coms_routes.py                   - COMs tab: Telegram message feed, config, migration status
platform_v2/tools/agent_academy/competency_routes.py             - Competency testing + department readiness
platform_v2/services/telegram_service.py                         - Unified Telegram: A.R.C.H.I.E. voice, source_agent, message logging
# NOTE: ai_bridge/{bridge_dispatcher,orchestration_engine,smart_router}.py are back-compat shims only.
# New code must import from tools.department_hq.services.* — enforced by scripts/check_agent_single_writer.py
```

## Pattern Reference

### Department HQ → Agent Service Pattern
- All agent mutations go through `agent_service.py` — no direct SQL on agent tables
- 17 departments across 5 floors: BRIDGE, OPERATIONS, ENGINEERING, CREATIVE, SERVICES
- Department HQ module: 12 tabs (Overview, Org Chart, Roster, Work Tracking, Performance, C.R.E.E.D., Social, Devices, Dispatch, Fleet, Contractors, COMs)
- Agent Academy module: 5 tabs (Benchmarks, Training, A/B Testing, Skills, Reports)
- Agent lifecycle: `agent_service.create_agent()`, `.update_agent()`, `.deactivate_agent()`

### Bridge Dispatch → ALL LLM Calls (ADR-013)
- `get_dispatcher()` singleton — never instantiate directly
- `dispatch()` or `dispatch_json()` for all inference
- `get_crew_manifest()` for roster data
- Escalation: home → capability → cross-department → fleet → cloud

### LCARS Modals → bm- Classes
- `bm-overlay > bm-shell > bm-frame + bm-content > bm-header + bm-body + bm-footer`
- Set `--bm-accent` for theming
- Reference: `bridge.html` lines 9209-9249

### Agent Roster
- `agents` table = single source of truth (131 non-decommissioned: 34 AI + 90 internal + 5 contractor)
- 34 AI agents (worker_type='ai') across 17 departments — 29 active, 5 barracked
- 17 departments (News & Media added 2026-04-14 with 6 AI agents)
- 1 agent = 1 department (managed via `agent_service.py`)
- Shift states: active, deployed, barracked, off_duty, winding_down, cooldown
- A.R.C.H.I.E. = Executive Office (COO), P.R.O.B.E. = Engineering director, V.I.G.I.L. = Security & Compliance director
- Column is `worker_type` (ai/internal/contractor) — NOT `agent_type`
- All agent mutations go through `agent_service.py` — no direct SQL on agent tables

### UI
- Live glow: `sc-live` (pulsing teal) vs `sc-static` (dim)
- Single status badge per agent
- `_renderUnifiedAgentCard()` for all agent cards
- `openAgentProfileFromBridge(hubAgentId)` for profiles
- Responsive: 480px / 768px / 1024px breakpoints

### Model Management
- 3 tiers: GPU (VRAM) > CPU (RAM) > Cold (disk)
- `model-control` endpoint for load/unload (accepts `node_id`)
- ComfyUI VRAM swap before SDXL generation

## Critical Technical Rules

1. **Read before modify** — Check existing code patterns first
2. **Two .env files** — Root `.env` and `platform_v2/.env` must match
3. **Module perms** — Add to BOTH `rbac.py` AND `module_registry.py`
4. **Keep indexes in sync** — Memory files → MEMORY.md. Architecture changes → rules files + CLAUDE.md
5. **Dev HQ after every commit+push**:
   - `mcp create_task` for new work
   - `mcp complete_task` with notes when done
   - `mcp log_decision` for architectural choices
   - `mcp update_project_understanding` after working on a project

## Common Errors

| Error | Fix |
|-------|-----|
| `archie_database` not found | Run inside Docker container |
| `localhost:5432 refused` | Use `192.168.1.200` for DB_HOST |
| `TemplateNotFound` | Use `tools/` prefix in path |
| Module not showing | Check both `rbac.py` + `module_registry.py` |
| Ollama resource contention | Unload non-essential models before inference |
| Agent column errors | `current_mood` (not mood), `skill_category` (not category), `proficiency_level` (not level) |

## Commands

```bash
docker compose up -d                          # Start
docker compose restart archie_platform        # Restart
docker logs -f archie_platform                # Logs
docker exec -it archie_database psql -U archie -d archie  # DB
```

## Skills

- `/archie-boot` - Session start protocol (MANDATORY)
- `/archie-status` - Platform health check
- `/archie-module` - Create/modify modules
- `/archie-deploy` - Safe deployment
- `/archie-patterns` - Code patterns & conventions
- `/archie-search` - Search knowledge base
- `/archie-project` - Project & task management
- `/archie-work` - Start/track work sessions
