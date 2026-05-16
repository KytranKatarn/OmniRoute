---
globs: ["platform_v2/tools/media_studio/**", "platform_v2/tools/game_studio/**"]
---

# Creative Studios Rules

## Modules
- **Media Studio** — `/tools/media-studio`, `media_studio_bp` (20+ routes, GPU-aware)
- **Game Studio** — `/tools/game-studio`, `game_studio_bp` (15+ routes)

## Media Studio (Primary)
- Full LCARS module with own templates/ and static/ directories
- Blueprint: `template_folder="templates"`, `static_folder="static"` (Blueprint gotcha ADR-021)
- 9,385 LOC · 98+ routes · 19 service modules
- Local SDXL via ComfyUI (hub or fleet) + cloud contractors (OpenAI, Gemini, HuggingFace, Cloudflare AI, Together, Pollinations) — see ADR-005
- VRAM swap management on hub (unloads Ollama before SDXL)

## Key DB Tables
- `media_generation_queue` — queued generation requests. Key columns: `status` (pending/dispatched/generating/completed/failed), `params` JSONB (model, prompt, **provider**, **fleet_node**), `result_media_id` FK to media_library
- `media_library` — completed media assets (file_path, thumbnail_path, owner_type/owner_id, prompt, seed, metadata)
- `agent_portraits` — UNIQUE(agent_id), holds canonical_image_path, identity_prompt, face_seed, ip_adapter_ref_path
- `contractor_providers` — cloud API registry. `capabilities` JSONB array; query `WHERE capabilities ? 'image_gen'` for image providers
- `cloud_model_usage` — cost ledger (audio/video wired; image cost logging is v2 task #2941)

## Image generation routing (ADR-005, 2026-05-16)
ALL image media_type submissions go through the worker queue. Single entry point:

```
submit_generation(media_type='image', ...)
  → INSERT media_generation_queue ... status='pending'
  → return {queue_id, status:'pending'}   (early-return for ALL image jobs)
  → [worker, every 30s]
  → media_generation_worker claims pending row (no provider filter)
  → calls generate_via_comfyui(queue_id)
     → if params.provider in {contractor keys}: → _generate_via_contractor
        → external_providers.generate_media(provider_key, request)
        → adapter saves file to static/media/images/<date>/
        → on_generation_complete → media_library row
     → else (default / params.provider=comfyui): existing ComfyUI workflow
        → fleet routing via get_best_comfyui_url(model_name)
        → POST /prompt to .246 / .245 / hub
        → poll /history, fetch output
        → on_generation_complete → media_library row
```

Don't reintroduce the dispatcher sync path for image gen — it has an unbound-local bug on `model` at `department_dispatcher.py:4864` AND blocks the web thread on multi-minute cloud APIs. ADR-013 ("all inference through Bridge") is technically violated for cloud image gen; acceptable trade-off documented in ADR-005 (#599).

## Image provider selector dropdown (PR #766)
- Endpoint: `GET /tools/media-studio/api/image-providers`
- Returns `{auto, local[], cloud_free[], cloud_paid[]}` — local from `/mnt/data2/comfyui/models/checkpoints/` enumeration, cloud from `contractor_providers WHERE capabilities ? 'image_gen'`
- Value format in `<select>`: bare filename for local (e.g., `sd_xl_base_1.0.safetensors`); `provider:<key>` for cloud (e.g., `provider:openai`, `provider:pollinations`)
- Backward compat: bare filenames keep working (no prefix parsing needed for the existing comfyui path)
- IP-Adapter face anchoring auto-disabled for contractor picks (most clouds can't honor face ref)
- Provider default model in `PROVIDER_DEFAULT_MODEL` dict in `services/generation_service.py`

## Variant provenance badges (PR #765)
- `portrait_service.get_agent_portrait` LEFT JOINs `media_generation_queue` on `result_media_id` to surface `params.model`, `params.fleet_node`, `params.provider`
- Variant tiles render two transparent corner badges:
  - **Bottom-left**: GPU label from `fleet_node` (`starship_76583490e36955ab` → "RTX 3070", `archie-starbase` → "Quadro M4000")
  - **Bottom-right**: provider name (e.g., "OpenAI", "Pollinations") OR model name (e.g., "RealVisXL", "SDXL Turbo") — provider wins when set

## Fleet ComfyUI gotchas
- Fleet routing in `comfyui_manager.get_best_comfyui_url(model_name)` — checks `remote_nodes.extra_capabilities.comfyui_models` JSONB array, routes only if model is on the node
- After OTA pulls (`mesh_sync_log` sync_type=`checkpoint_pull`): manually update `extra_capabilities.comfyui_models` for the node (auto-registration only catches some files)
- OTA URL bug pattern (KB mistake_learned #266408): wrong URL `/api/fleet/checkpoints/<file>` returns 200 + HTML login page (~11 KB) instead of the binary. CORRECT URL: `/tools/department-hq/api/fleet/checkpoints/<file>`. Always use the prefixed URL when inserting `mesh_sync_log` rows.
- Cold-load poll timeout 600s (sd_xl_base ~6.9GB takes 7-8 min cold on RTX 3070)
- On fleet timeout: fail-loud (reaper retries every 10min) — DO NOT add silent hub fallback

## Game Studio
- Blueprint at `tools/game_studio/`
- Template at `templates/tools/game_studio.html`
- Game design and development tools

## Gotchas
- Media Studio `template_folder="templates"` — has own templates subdir (Blueprint gotcha ADR-021)
- VRAM swap (hub only): must unload GPU models before SDXL generation, restore after
- Local hub checkpoints: RealVisXL_V4.0, juggernautXL_v9, sd_xl_base_1.0, sdxl_turbo, ltx-video-2b-v0.9, v1-5-pruned-emaonly. Node ComfyUI has fewer — check `extra_capabilities.comfyui_models` before routing
- Cloud API keys live in BOTH `.env` files (root + platform_v2). Only `GEMINI_API_KEY` is set as of 2026-05-16; Pollinations needs no auth
- New cloud provider adapter goes in `ai_bridge/external_providers.py` `adapters` dict at line ~468; follow `_pollinations_image_adapter` pattern: HTTP call → save to `/app/static/media/images/<date>/` → return `{success, file_path, metadata}` with `cost_usd` in metadata
