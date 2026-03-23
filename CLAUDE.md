# A.R.C.H.I.E. Platform

**Version**: 5.32.0 | **Host**: 192.168.1.200 | **Status**: Operational

---

## Session Start Protocol (MANDATORY)

Every new session MUST begin with one of:
- Run `/archie-boot` (preferred — guided session boot)
- Call `mcp__archie__session_briefing` with the task topic (one-call alternative)

**The knowledge base has 18,000+ entries with embeddings. Search before building. Search before asking.**
- `search_knowledge` — semantic + text search across all knowledge types
- `recall_context` — recall past context for a topic
- `search_knowledge` with types: ["mistake_learned"] — prevent repeating costly errors

**The user is REMOTE** — always use 192.168.1.200, never localhost.

---

## Critical Rules

1. **Read before modify** - Check existing code patterns first
2. **Test in Docker** - `docker exec archie_platform python3 script.py`
3. **Two .env files** - Root `.env` and `platform_v2/.env` must match
4. **Module perms** - Add to BOTH `rbac.py` AND `module_registry.py`
5. **Dev HQ is the source of truth** - After every commit+push, update Dev HQ:
   - `mcp create_project` / `create_task` for new work
   - `mcp complete_task` with notes when done
   - `mcp log_decision` for architectural choices
   - `mcp store_memory` (vault_note) for roadmap updates
   - `mcp update_project_understanding` after working on a project

## Quick Reference

| Resource | Location |
|----------|----------|
| Platform | http://192.168.1.200:3000 |
| Dev HQ | http://192.168.1.200:3000/dev-hq |
| Docs | `knowledge_base` table → Dev HQ Knowledge tab or MCP `search_knowledge` |
| Modules | `/mnt/archie_brain/platform_v2/tools/` (50 modules) |
| MCP Tools | 79 tools via `.mcp.json` (incl. `session_briefing`) |
| Projects | `unified_projects` table → MCP `get_projects` / `create_task` |

## Architecture (7 Systems)

1. **Knowledge Base** - `knowledge_base` table (~18,000 active entries, 99% embedded; ~20 archived as `archie_v1`)
2. **AI Bridge** - `/ai_bridge/archie_bridge.py` (multi-model router)
3. **Module System** - Flask Blueprints in `/platform_v2/tools/`
4. **Dev HQ** - Development command center (`/dev-hq`), projects, knowledge, schema, integrations
5. **Consciousness** - Knowledge analytics, AI processing, embedding coverage, emotional intelligence
6. **Improvement Workflow** - Scan → Proposal → Sandbox → Deploy
7. **Orchestration Engine** - `ai_bridge/orchestration_engine.py` (intent→route→delegate→execute pipeline, GPU-aware, IAAE-governed)
8. **IAAE Transparency** - `/iaae` public page (no auth), live governance stats, agent welfare, ethics constraints

## Source of Truth

| Data | Location | Access |
|------|----------|--------|
| **Documentation & Knowledge** | `knowledge_base` table | Dev HQ Knowledge tab, MCP `search_knowledge`, MCP `store_memory` (use `knowledge_type='vault_note'` for docs) |
| **Projects & Tasks** | `unified_projects` + `unified_tasks` tables | MCP `get_projects`, `create_project`, `create_task`, `complete_task` |
| **Decisions** | `project_decisions` table | MCP `log_decision` |
| **Module Code** | `/platform_v2/tools/` filesystem | Direct file access |

| **Roadmaps** | `knowledge_base` vault_notes with "roadmap" tag | MCP `search_knowledge`, `store_memory` |

**NO filesystem docs** — `/docs/` is archived (git history only). **NO TODO_LIST.md** — use `unified_tasks` table. **NO ad-hoc memory tracking** — use Dev HQ projects + tasks + decisions.

## Key Files

```
platform_v2/app.py                - Flask app + |localtime filter
platform_v2/module_registry.py    - Module definitions
platform_v2/rbac.py               - Permissions
platform_v2/database.py           - DB connection
platform_v2/static/js/archie-time.js  - Global timezone-aware timestamp formatter
platform_v2/static/js/station-ops.js  - Shared station operations component
platform_v2/static/css/station-ops.css - Shared station ops CSS
ai_bridge/archie_bridge.py        - AI routing
ai_bridge/orchestration_engine.py - Orchestration pipeline (intent→route→execute)
ai_bridge/smart_router.py         - GPU-aware model routing
ai_bridge/knowledge_analyzer.py   - Knowledge extraction (Ollama qwen2.5:7b)
ai_bridge/embedding_service.py    - Vector embeddings (nomic-embed-text)
```

## Pattern Reference

### Station Operations Pattern
- Use `StationOps` class from `station-ops.js` + `station-ops.css`
- Constructor: `new StationOps({stationCode, moduleSource, agentsElId, jobsElId, commandsElId, statusElId, commands, dataUrl})`
- 10 canonical stations: COMMAND, ANALYTICS, CREATIVE, ENGINEERING, COMMUNICATIONS, RESEARCH, SECURITY, LOGISTICS, DIPLOMATIC, OPERATIONS
- Each station: 2 primary agents max + 1 auxiliary
- Consciousness module is the gold standard implementation

### Agent Roster Rules
- `agents` table is single source of truth for all roster data
- 1 agent = 1 station (DB constraint `idx_station_assignments_one_per_agent`)
- Shift states: active (hub), deployed (on node), barracked (reserve), off_duty, winding_down, cooldown
- ARCHIE + Vigil always on COMMAND (ARCHIE primary, Vigil secondary)
- Deployed agents show only in their node's section, not hub groups
- Advisory notification when barracked ≤ 5 (no auto-creation — Decision #229)

### Bridge Dispatch Pattern
- ALL inference through Bridge dispatcher — `dispatch()` or `dispatch_json()` (ADR-013)
- `get_dispatcher()` singleton — never instantiate `BridgeDispatcher()` directly
- `get_crew_manifest()` for roster data
- `ensure_model_ready()` auto warm-boots before dispatch
- Escalation: home station → capability → cross-station → fleet node → cloud
- Fleet dispatch: `_find_fleet_agent()` + `_dispatch_to_node()`

### Node Fleet Pattern
- Nodes register in `remote_nodes`, agents in `node_agents` (FK `hub_agent_id` → `agents.id`)
- Node Ollama queried directly: `http://{hostname}:{port}/api/*`
- `check_fleet_health()` monitors heartbeats every 30s
- Node offline: agents return to barracks. Online: agents restored or new assigned
- `model_load_state` table persists loaded models for restart recovery
- Node heartbeat sends: cpu_model, gpu_model, gpu_vram_gb, ram_gb, ollama_models

### UI Patterns
- LCARS tablet modals: `bm-overlay` + `bm-shell` + `bm-frame` + `bm-content`
- Live data glow: `sc-live` (pulsing teal) vs `sc-static` (dim) CSS classes
- Single status badge per agent: ON DUTY / DEPLOYED / WORKING / BARRACKED / OFF DUTY
- Collapsible roster sections with color-coded borders
- `_renderUnifiedAgentCard()` for all agent card rendering
- Agent profile always from Bridge: `openAgentProfileFromBridge(hubAgentId)`

### Model Management
- 3 tiers: GPU (VRAM) > CPU (RAM) > Cold (disk)
- `model-control` endpoint handles load/unload for hub + nodes (accepts `node_id`)
- ComfyUI VRAM swap: `_vram_swap_for_comfyui()` / `_vram_restore_after_comfyui()`
- Nodes no security reserve (managed from hub)
- `_save_model_state()` / `_restore_model_state()` for restart recovery

## Common Errors

| Error | Fix |
|-------|-----|
| `archie_database` not found | Run inside Docker container |
| `localhost:5432 refused` | Use `192.168.1.200` for DB_HOST |
| `TemplateNotFound` | Use `tools/` prefix in path |
| Module not showing | Check both `rbac.py` + `module_registry.py` |

## Commands

```bash
docker compose up -d                          # Start
docker compose restart archie_platform        # Restart
docker logs -f archie_platform                # Logs
docker exec -it archie_database psql -U archie -d archie  # DB
```

## Code Health & Audit Workflow

**Tracking**: Consciousness → Code Health tab (6th tab)
- `code_metrics_snapshots` table — daily auto-scan at 3:00 AM (agent loop job #40)
- `code_audit_log` table — records every module audit with before/after line counts
- Pattern compliance scan at 4:00 AM (job #41) — flags direct Ollama calls, missing user_id

**After completing any module audit:**
1. Run `scan_codebase()` before and after changes
2. Call `log_audit(module_name, category, files_reviewed, lines_before, lines_after, issues_found, issues_fixed, notes, status)`
3. Commit changes with descriptive message
4. Verify Code Health tab reflects the changes

**Pattern Rules (NEVER violate):**
- ALL LLM calls → `bridge_dispatcher.dispatch()` or `dispatch_json()` (ADR-013)
- ALL SaaS data → scoped by `user_id` (per-user isolation)
- ALL station panels → copy Consciousness pattern exactly (StationOps constructor)
- ALL modals → LCARS tablet design (bm- CSS classes)
- ALL features → read existing code FIRST, never assume

## Skills (Use These!)

- `/archie-boot` - Session start protocol (MANDATORY)
- `/archie-status` - Platform health check
- `/archie-module` - Create/modify modules
- `/archie-deploy` - Safe deployment
- `/archie-patterns` - Code patterns & conventions
- `/archie-search` - Search knowledge base
- `/archie-project` - Project & task management
- `/archie-work` - Start/track work sessions (NEW)

## Token Saving Tips

1. Use `/clear` between unrelated tasks
2. Be specific: "Fix line 45 in auth.py" not "improve auth"
3. Use subagents for file searches (Task tool)
4. Check MCP tools before reading files
5. Use skills instead of re-explaining workflows

---

*Use `/archie-patterns` for code examples, `/archie-status` for health checks*
