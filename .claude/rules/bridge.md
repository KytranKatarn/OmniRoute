---
globs: ["platform_v2/tools/bridge/**", "ai_bridge/bridge_dispatcher.py"]
---

# Bridge Command Rules (Audited 2026-03-18)

## File Structure (split from monolithic routes.py)
- `routes.py` — 1,379 lines, core routes (dashboard, stats, traffic, LLM monitor)
- `helpers.py` — 282 lines, shared caches (_get_cached_ollama_tags/ps/hw_capacity)
- `node_routes.py` — 2,118 lines (38 routes — nodes, approval, assignments)
- `station_routes.py` — 2,028 lines (36 routes — stations, actions, benchmarks)
- `agent_routes.py` — 1,530 lines (24 routes — CRUD, skills, workload compliance max 3 jobs)
- `crew_routes.py` — 1,302 lines (19 routes — manifest, lounge, training, IAAE)
- `provider_routes.py` — 1,159 lines (19 routes — ComfyUI, routing, providers)
- `dispatch_routes.py` — 724 lines (9 routes — activity, jobs, analytics)
- `mission_routes.py` — 370 lines (13 routes — SSE, command, profiles, flows)
- `mesh_routes.py` — 954 lines (13 routes — node lending, sync, cluster)
- `bridge.html` — 1,723 lines (pure HTML, CSS/JS extracted)
- `bridge.css` — 7,785 lines (external, cacheable)
- `bridge.js` — 11,675 lines (external, cacheable)
- `bridge_dispatcher.py` — 5,400 lines (dispatch, escalation, crew manifest)
- Pattern: `register_*_routes(bp, admin_required)` in `__init__.py` (matches Consciousness ADR-045)

## Patterns
- Station codes: COMMAND, ANALYTICS, CREATIVE, ENGINEERING, COMMUNICATIONS, RESEARCH, SECURITY, LOGISTICS, DIPLOMATIC, OPERATIONS
- Caches in `helpers.py`: `_get_cached_ollama_tags/ps/hw_capacity()` — 30s TTL each
- Agent manifest: `get_crew_manifest()` in dispatcher, consumed by crew_routes.py
- GPU tools: `gpu_tools` array on manifest entries (ComfyUI for Pixel)
- Three-tier readiness: loaded/swap/barracked (ADR-078)
- Workload compliance: max 3 station assignments + max 3 active bridge_jobs per agent

## Node/Starship Integration
- Starship module = remote view of Bridge (should NOT generate own agents — Task #1023)
- Node lifecycle: register → heartbeat (30s) → health → station assignments
- Cross-node: mesh_routes.py handles agent lending, sync, cluster overview
- Heartbeat updates dispatcher cache with fleet agent welfare data

## DB Gotchas
- `bridge_jobs`: uses `agent_name` (varchar, not agent_id), `completed_steps`/`total_steps` (not progress), no `started_at`
- `task_execution_log`: has `station_code` directly — use it, don't join through `station_assignments`
- `agents`: `display_name` for UI, `name` for code. `image_model` column for ComfyUI agents
- `station_assignments` (not `station_agents`), station_id is integer (no stations table)
- Agent names: ALL capitalized, unique. Duplicates fixed 2026-03-18 (pulse→Tempo, quill→Scribe)

## CSS
- External file: `static/css/bridge.css` (NOT inline in template)
- Prefix: none (bridge-specific classes like `crew-*`, `roster-*`)
- LLM badges: `.crew-llm-badge.loaded/.swap/.barracked/.cloud`
