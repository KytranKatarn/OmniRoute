# ComfyUI Agent Integration — Design Doc

**Date**: 2026-03-06
**Status**: Implemented (Phase 1 — Dispatcher Integration)
**Project**: ComfyUI as Pixel's Image Generation Skill

## Problem

ComfyUI is running as a Docker service with GPU access, but it's completely disconnected from the agent roster and Bridge dispatcher. Modules that need image generation have no standardized way to request it, and there's no workload tracking, VRAM visibility, or model management through the existing UI.

## Decision

Integrate ComfyUI as **Pixel's unique skill** — not a separate agent, but a tool that Pixel (and only Pixel) can use. All image generation routes through Bridge -> Pixel -> ComfyUI, same as any other agent dispatch.

## Architecture

### Current Flow (Text Generation)
```
Module -> Bridge Dispatcher -> find agent with capability -> Ollama API -> result
```

### New Flow (Image Generation)
```
Module -> Bridge Dispatcher -> Pixel (image_generation capability) -> ComfyUI API -> result
```

The dispatcher already maps `image_generation` -> `CREATIVE` station. Pixel already has `image_generation: true` in capabilities. The missing piece is the **execution path** — when the dispatcher picks Pixel for an image job, it needs to call ComfyUI instead of Ollama.

## Changes Required

### 1. Agent Model Field — Dual Model Support

Pixel currently has `model: qwen2.5vl:7b` (vision LLM). She needs both:
- **LLM model**: `qwen2.5vl:7b` — for analyzing/describing images (Ollama)
- **Image model**: `sd_xl_base_1.0.safetensors` — for generating images (ComfyUI)

**Option A** (Recommended): Add `image_model` column to agents table. Only Pixel would have this set. The dispatcher checks: if job type is `image_generation` AND agent has `image_model`, route to ComfyUI service instead of Ollama.

**Option B**: Store in agent `metadata` JSONB field as `{"comfyui_model": "sd_xl_base_1.0.safetensors"}`. Less clean but no schema change.

### 2. Bridge Dispatcher — ComfyUI Execution Path

In `bridge_dispatcher.py`, the `request_work()` method currently always calls Ollama. Add a branch:

```python
def request_work(self, ...):
    agent = self._select_agent(capability)

    if capability == "image_generation" and agent.get("image_model"):
        return self._execute_comfyui(agent, request)
    else:
        return self._execute_ollama(agent, request)
```

`_execute_comfyui()` would:
1. Mark Pixel as busy (same as any agent)
2. Call `comfyui_service.generate_image(prompt, model=agent.image_model, ...)`
3. Record the job in bridge_jobs (duration, success, file path)
4. Mark Pixel as idle
5. Return result with file_path

### 3. VRAM Management — Unified Display

The Bridge Command "Hardware" or "Roster" panel currently shows Ollama models and their VRAM usage via `/api/ps`. Extend this to also query ComfyUI's `/system_stats` endpoint:

```
GPU: Quadro M4000 (8GB)
-------------------------------------
Ollama:   smollm2:1.7b     1.7GB  [VRAM]
ComfyUI:  sd_xl_base_1.0   6.5GB  [VRAM]   <- NEW
-------------------------------------
Total:    8.2GB / 8.0GB    [SWAP WARNING]
Free:     0.0GB
```

Key behaviors:
- Show ComfyUI loaded checkpoint in the same VRAM list as Ollama models
- Warn when SDXL + smollm2 can't coexist (8.2GB > 8GB)
- Model swap: when Pixel gets an image job, auto-unload conflicting Ollama models if needed, generate, then reload

### 4. Model Control — Load/Unload in Bridge UI

The existing model load/unload buttons in Bridge Command work via Ollama's API. Add ComfyUI model management to the same interface:

- ComfyUI checkpoints appear in the model list alongside Ollama models
- Provider column shows "comfyui" vs "ollama"
- Load/unload calls the appropriate API
- ComfyUI's `/free` endpoint to unload models

### 5. Module Access — Standard Bridge Interface

Any module that wants image generation calls the same Bridge API:

```python
# From any module:
result = dispatcher.request_work(
    capability="image_generation",
    prompt="a logo for my company",
    params={"width": 1024, "height": 1024, "steps": 20}
)
# Returns: {success, file_path, agent_name, duration_ms, ...}
```

Modules don't need to know about ComfyUI — they just request `image_generation` capability and Bridge handles the rest.

### 6. Job Tracking — Same as Any Agent

Image generation jobs show up in:
- Bridge Command job history (with thumbnails)
- Pixel's agent stats (jobs completed, avg duration)
- Station activity feed
- Benchmark results

## Migration

```sql
-- Add image_model column
ALTER TABLE agents ADD COLUMN image_model VARCHAR(200);

-- Set Pixel's ComfyUI model
UPDATE agents SET image_model = 'sd_xl_base_1.0.safetensors' WHERE name = 'Pixel';
```

## Files to Modify

| File | Change |
|------|--------|
| `database/migrations/133_agent_image_model.sql` | Add `image_model` column |
| `ai_bridge/bridge_dispatcher.py` | Add `_execute_comfyui()` path in `request_work()` |
| `ai_bridge/comfyui_service.py` | Already done — generation service exists |
| `platform_v2/tools/bridge/routes.py` | Add ComfyUI models to VRAM display, model control |
| `platform_v2/templates/tools/bridge.html` | Show ComfyUI in model list + VRAM panel |
| `platform_v2/services/benchmark_service.py` | Use dispatcher path instead of direct ComfyUI calls |

## VRAM Swap Strategy

With 8GB VRAM:
- smollm2:1.7b (chat) + SD 1.5 (4GB) = 5.7GB -> fits
- smollm2:1.7b (chat) + SDXL (6.5GB) = 8.2GB -> doesn't fit

When Pixel gets an image job with SDXL:
1. Unload smollm2 from Ollama GPU (move to CPU-only)
2. Load SDXL in ComfyUI
3. Generate image
4. Unload SDXL from ComfyUI
5. Reload smollm2 on GPU

This swap adds ~30-60s overhead. For SD 1.5, no swap needed — both fit.

Future: With a 12GB+ GPU, both coexist and no swapping is needed.

## Not In Scope (Future)

- Node system / multi-node GPU distribution
- Video generation capabilities
- img2img / inpainting / ControlNet (ComfyUI supports these, but wire up later)
- Multiple image agents (only Pixel for now)
- ComfyUI web UI exposure to platform users
