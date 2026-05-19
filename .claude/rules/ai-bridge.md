---
globs: ["ai_bridge/**"]
---

# AI Bridge Rules

## Architecture
- ALL LLM inference routes through Bridge dispatcher (ADR-013, ADR-002). No direct Ollama from modules.
- Direct Ollama GET for `/api/tags`/`/api/ps` is acceptable (not inference).
- **Dispatcher physically lives in Department HQ** (Project #244 Phase 2, 2026-04-11):
  - `platform_v2/tools/department_hq/services/department_dispatcher.py` — dispatch entry point (renamed from `bridge_dispatcher`, Decision #441)
  - `platform_v2/tools/department_hq/services/orchestration_engine.py` — 8-step pipeline (intent→IAAE→welfare→route→agent→GPU→execute→log)
  - `platform_v2/tools/department_hq/services/smart_router.py` — 11-tier escalation, GPU-aware
- `ai_bridge/{bridge_dispatcher,orchestration_engine,smart_router}.py` are **back-compat shims only** (shim filenames retain the old `bridge_dispatcher` name). New code must import from `tools.department_hq.services.*` — enforced by `scripts/check_agent_single_writer.py`.
- Still in `ai_bridge/`: `archie_bridge.py` (intent+cost), `external_providers.py` (OpenAI-compatible adapters), `knowledge_analyzer.py`, `embedding_service.py`, `db.py`.

## Ollama Config

### Hub (192.168.1.200 / Quadro M4000)
- Host: 192.168.1.200:11434 | Docker: `host.docker.internal:11434`
- GPU: Quadro M4000 (8GB VRAM) | RAM: 128GB
- **MAX_LOADED_MODELS=6 | KEEP_ALIVE=30m | NUM_PARALLEL=1** (updated 2026-05-19)
- Warm model set (GPU+CPU simultaneously):
  - GPU: `qwen2.5:1.5b` (1.3GB) + `llama3.2:3b` (2.6GB) = 3.9GB VRAM
  - CPU: `qwen2.5:7b` + `mistral:7b` + `gemma3:12b` + `dolphin3:latest` = ~23GB RAM
- Lifecycle: load-on-dispatch via `services/model_service.py:ensure_model_ready`, auto-unload via Ollama KEEP_ALIVE. Observer `ollama_lifecycle_telemetry` (5m) logs state + alerts on stall (#1898).
- Warmup: `_warmup_ollama_models()` in app.py — priority by dispatch frequency, stops at <25GB free
- Cloud models (`:cloud` suffix) skip local loading
- Modelfiles at `/mnt/llm_drive/ollama/Modelfile.*`
- Model storage: `/mnt/llm_drive/ollama/models/` (Samsung 840 SSD, systemd env OLLAMA_MODELS)

### Starship-246 (100.64.0.3 / RTX 3070 8GB / 32GB RAM)
- Container: `archie_node_ollama` port 11434
- **MAX_LOADED_MODELS=3 | KEEP_ALIVE=10m | NUM_PARALLEL=2** (set via OTA 2026-05-19)
- Warm model set: `qwen2.5:1.5b` GPU + `llama3.2:3b` GPU + `qwen2.5:7b` CPU
- Available: qwen2.5:7b, qwen2.5:1.5b, llama3.2:3b, mistral:7b, dolphin3:latest, gemma3:12b

### Starship-245 (100.64.0.6 / RTX 3070 4GB / 12GB RAM)
- Container: `archie_node_ollama` port 11434
- **MAX_LOADED_MODELS=2 | KEEP_ALIVE=10m | NUM_PARALLEL=1** (set via OTA 2026-05-19)
- Warm model set: `qwen2.5:1.5b` GPU + `llama3.2:3b` CPU (4GB VRAM limit)
- Available: qwen2.5:7b, qwen2.5:1.5b, llama3.2:3b, mistral:7b, dolphin3:latest

### Key insight: GPU+CPU simultaneous loading
- Load small fast models on GPU, large models on CPU RAM
- qwen2.5:7b on GPU evicts others (uses ~5GB + KV cache reservation)
- Pattern: `num_gpu=0` forces CPU-only for a model, freeing VRAM for smaller GPU models
- Hub 128GB RAM can hold 6+ models simultaneously

## ComfyUI
- Port 8188 (Docker `archie_comfyui`) | Pixel is sole image gen agent
- Checkpoints: `/mnt/data2/comfyui/models/checkpoints/`
- VRAM swap: SDXL auto-unloads Ollama GPU models before generating

## Code Structure (Audited 2026-03-18)
- Shared DB: `ai_bridge/db.py` — single `get_db()` and `get_db_dict()` for all ai_bridge modules (replaces 19 local copies)
- All DB calls use `try/finally: conn.close()` pattern — no connection leaks
- No hardcoded passwords — all use `os.getenv("DB_PASSWORD", "")`
- `archie_bridge.py`: `archie_bridge()` split into orchestrator + 4 helpers (`_parse_bridge_intent`, `_select_bridge_model`, `_execute_bridge_call`, `_log_bridge_result`)
- `agent_loop.py`: `request_approval()` split into orchestrator + 4 helpers (`_validate_approval_request`, `_check_existing_approval`, `_get_effective_tier`, `_create_approval_record`)
- `department_dispatcher.py`: Input validation on `dispatch()` and `dispatch_json()`
- Files reduced: 80→45 root Python files after relocating module-specific code

## Dispatch API (MANDATORY)
- New canonical import: `from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json, get_dispatcher`
  - Inside `department_hq/services/`, use relative: `from .department_dispatcher import get_dispatcher`
  - From `department_hq/` routes (one level up), use: `from .services.department_dispatcher import get_dispatcher`
- `dispatch()` / `dispatch_json()` are module-level functions — use these, not `get_dispatcher().dispatch()` (the instance method is `request_work()`).
- `dispatch()` returns `DispatchResult` — always check `.success` and use `.response`.
- `get_agent_cache()` keys skills by `skill_name` (not `skill_category`) — capability matching depends on this.
- Legacy `from ai_bridge.bridge_dispatcher import ...` still works via shim but emits `DeprecationWarning` and is **blocked for new files** by the K.I.N. guardrail.

## Key Gotchas
- `num_ctx` inflates VRAM massively (phi3.5: 2GB disk but 5.47GB with 2048 ctx)
- qwen3-coder-cpu needs 600s timeout (55GB, ~9min cold load)
- Model disk size != runtime size (multiply by ~1.3 for runtime estimate)
- Import `from db import get_db` (NOT local `get_db()` definitions)
- All exceptions must be specific (no bare `except:`) — catch `Exception` minimum
