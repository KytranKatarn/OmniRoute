# Creative Studios Rules

## Modules
- **Media Studio** — `/tools/media-studio`, `media_studio_bp` (20+ routes, GPU-aware)
- **Game Studio** — `/tools/game-studio`, `game_studio_bp` (15+ routes)

## Media Studio (Primary)
- Full LCARS module with own templates/ and static/ directories
- Blueprint: `template_folder="templates"`, `static_folder="static"`
- Uses Bridge dispatch for GPU-aware image/video/audio generation
- ComfyUI integration for image generation
- VRAM swap management (unloads Ollama models before SDXL)

## Key DB Tables
- `media_generation_jobs` — generation job tracking
- `media_assets` — generated media assets
- `generation_queue` — queued generation requests

## Bridge Dispatch
- Media Studio uses `get_dispatcher()` for GPU-tiered fleet routing
- Image generation: ComfyUI checkpoints (SDXL, SD1.5)
- Audio/video: specialized model dispatch

## Game Studio
- Blueprint at `tools/game_studio/`
- Template at `templates/tools/game_studio.html`
- Game design and development tools

## Gotchas
- Media Studio `template_folder="templates"` — has own templates subdir (Blueprint gotcha ADR-021)
- VRAM swap: must unload GPU models before SDXL generation, restore after
- ComfyUI checkpoints: RealVisXL, Juggernaut, SDXL Base/Turbo, SD1.5
- Node ComfyUI has fewer checkpoints than hub — check availability before routing
