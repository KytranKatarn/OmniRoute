---
globs: ["platform_v2/tools/bridge/**", "ai_bridge/bridge_dispatcher.py"]
---

# Bridge Command Rules

## Key Files
- `routes.py` — 7000+ lines, all API endpoints. `_get_cached_hw_capacity()` for hardware.
- `bridge.html` — 18000+ lines, all 5 tabs (Stations, Overview, Dispatch, Crew, Network)
- `bridge_dispatcher.py` — agent dispatch, escalation chain, crew manifest

## Patterns
- Station codes: COMMAND, ANALYTICS, CREATIVE, ENGINEERING, COMMUNICATIONS, RESEARCH, SECURITY, LOGISTICS, DIPLOMATIC, OPERATIONS
- `_get_cached_ollama_ps()` — 30s TTL cache for Ollama model state
- `_get_cached_hw_capacity()` — 30s TTL for GPU/RAM/model breakdown
- Agent manifest: `get_crew_manifest()` in dispatcher, consumed by routes.py
- GPU tools: `gpu_tools` array on manifest entries (ComfyUI for Pixel)
- Three-tier readiness: loaded/swap/barracked (ADR-078)

## DB Gotchas
- `bridge_jobs`: uses `agent_name` (varchar, not agent_id), `completed_steps`/`total_steps` (not progress), no `started_at`
- `task_execution_log`: has `station_code` directly — use it, don't join through `station_assignments`
- `agents`: `display_name` for UI, `name` for code. `image_model` column for ComfyUI agents.
- `station_assignments` (not `station_agents`)

## CSS
- Prefix: none (bridge-specific classes like `crew-*`, `roster-*`)
- LLM badges: `.crew-llm-badge.loaded/.swap/.barracked/.cloud`
