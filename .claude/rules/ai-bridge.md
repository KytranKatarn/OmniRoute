---
globs: ["ai_bridge/**"]
---

# AI Bridge Rules

## Architecture
- ALL LLM inference routes through Bridge dispatcher (ADR-013). No direct Ollama from modules.
- Direct Ollama GET for `/api/tags`/`/api/ps` is acceptable (not inference).
- Smart Router: `ai_bridge/smart_router.py` — 11-tier escalation, GPU-aware
- External providers: `ai_bridge/external_providers.py` — OpenAI-compatible adapters
- Orchestration: `orchestration_engine.py` — 8-step pipeline (intent->IAAE->welfare->route->agent->GPU->execute->log)

## Ollama Config
- Host: 192.168.1.200:11434 | Docker: `host.docker.internal:11434`
- GPU: Quadro M4000 (8GB VRAM) | RAM: 128GB
- RAM budget: 80% LLM (90% agents + 10% swap) / 20% host reserve (ADR-078)
- MAX_LOADED_MODELS=13 | KEEP_ALIVE=24h | NUM_PARALLEL=4
- Warmup: `_warmup_ollama_models()` in app.py — priority by dispatch frequency, stops at <25GB free
- Cloud models (`:cloud` suffix) skip local loading
- Modelfiles at `/mnt/llm_drive/ollama/Modelfile.*`
- Model storage: `/mnt/llm_drive/ollama/models/` (Samsung 840 SSD, systemd env OLLAMA_MODELS)

## ComfyUI
- Port 8188 (Docker `archie_comfyui`) | Pixel is sole image gen agent
- Checkpoints: `/mnt/data2/comfyui/models/checkpoints/`
- VRAM swap: SDXL auto-unloads Ollama GPU models before generating

## Key Gotchas
- `num_ctx` inflates VRAM massively (phi3.5: 2GB disk but 5.47GB with 2048 ctx)
- qwen3-coder-cpu needs 600s timeout (55GB, ~9min cold load)
- Model disk size != runtime size (multiply by ~1.3 for runtime estimate)
