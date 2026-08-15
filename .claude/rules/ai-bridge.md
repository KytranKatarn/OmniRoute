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

### Hub (192.168.1.200 / TITAN X 12GB + Quadro M4000 8GB)
- Host: 192.168.1.200:11434 | Docker: `host.docker.internal:11434`
- GPU: **2 cards since 2026-07-25** — `Device 0` **Quadro M4000 8GB** (CC 5.2) + `Device 1` **NVIDIA TITAN X (Pascal) 12GB** (CC 6.1). **20GB total.** | RAM: 128GB
  - Ollama enumerates BOTH and schedules per-GPU (verified in `journalctl -u ollama`: independent `gpu memory` lines per device UUID). No `CUDA_VISIBLE_DEVICES` is set — do not add one.
  - ⚠️ **CORRECTED 2026-07-27 (task #5271).** This file said "TITAN X is Device 0" — it is **Device 1**. `nvidia-smi --query-gpu=index,name` returns `0, Quadro M4000` / `1, NVIDIA TITAN X (Pascal)`. The old "TITAN is Device 0, so it is preferred for the larger model" inference was built on that false premise. Identify the cards by **UUID**, not index: TITAN = `GPU-93e51659…`, Quadro = `GPU-e20b1ba4…`.
  - ✅ **FIXED — the platform sees BOTH cards** (#5271, verified live 2026-07-28). `services/model_service.py` now exposes `_VRAM_TOTAL_GB = 20.0` (aggregate residency) and `_VRAM_LARGEST_GPU_GB = 12.0` (the per-model ceiling — see the SPANNING correction below; the value is a deliberate conservative clamp, but NOT because spanning is impossible), and `get_available_vram()` is clamped by `min(available, largest_card_free)`. The old `available >= budget * 0.9` rule is gone: it scaled *with* the budget, so raising the constant alone would have fixed nothing.
    ⚠️ **This entry asserted the OPPOSITE for some time after #5271 shipped** — "the platform does NOT see the TITAN's VRAM" — and sent a session off to re-fix already-working code (2026-07-28). Before acting on any VRAM claim in this file, verify it: `docker exec archie_platform python3 -c "import sys;sys.path.insert(0,'/app');import services.model_service as m;print(m._VRAM_TOTAL_GB, m._VRAM_LARGEST_GPU_GB)"` → expect `20.0 12.0`.
    **Live consequence worth re-testing:** `NUM_PARALLEL=1` below was chosen because >1 blew the KV cache on an **8GB-only** box. That premise died when the 12GB TITAN arrived — the throughput ceiling may now be movable (context on #5372).
  - ⚠️ **Mixed compute capability (6.1 vs 5.2)** — `remote_nodes.gpu_vram_gb` is set to **12** (largest single GPU), not 20; see the note in `fleet.md`. That value is a deliberate SAFETY clamp for per-model sizing, and it stands.
    🔴 **CORRECTED 2026-08-15 — this line used to justify it with "a model cannot span both cards". THAT IS FALSE.** Ollama spans them routinely. Measured live from `journalctl -u ollama`:
    `load request="{... GPULayers:49[ID:GPU-e20b1ba4(Quadro) Layers:31(0..30) ID:GPU-93e51659(TITAN) Layers:18(31..48)]...}"` followed by `offloaded 49/49 layers to GPU`. Mixed CC does not prevent layer-splitting.
    **Why the correction matters operationally:** a spanning model consumes headroom on **BOTH** cards at once, which the placement logic does not anticipate. That is how VRAM budget reached **0.0 GB** on 2026-08-15 and forced `qwen2.5:7b` onto the **CPU** for ~4 min — producing a wall of `timeout after 240s` fact_check failures (89% failure that hour vs a 12% 24h baseline). NVML at the time: TITAN free 3.0/12.9 GB, Quadro free 3.4/8.6 GB — both genuinely full. See task **#5623**; a 7B on this pre-AVX2 Xeon cannot finish inside 240s, so CPU placement is a guaranteed failure, not a degraded path.
    Read placement decisions directly: `docker logs archie_scheduler | grep "model_service: placement"` → e.g. `placement qwen2.5:7b -> cpu (budget 0.0 GB < needed 5.9 GB)`.
  - ⚠️ **The inference Ollama is the HOST systemd service** (`systemctl status ollama`, owns :11434), NOT the `archie_ollama` container — that container exists but is not in the dispatch path. Probing it reports the wrong GPU inventory.
- **MAX_LOADED_MODELS=10 | KEEP_ALIVE=60m | NUM_PARALLEL=1** (updated 2026-06-19 — raised from 6/30m to use idle RAM: more models stay warm longer → fewer cold-loads. NUM_PARALLEL kept at 1 + no global num_ctx bump — those inflate the 8GB GPU KV-cache, the real ceiling. Config: `/etc/systemd/system/ollama.service.d/override.conf`; rollback backup `override.conf.bak.20260619-093056-ram-tweak`.)
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
- **MAX_LOADED_MODELS=6 | KEEP_ALIVE=60m | NUM_PARALLEL=1** (2026-07-06 — mirror the starbase warm-boot: hold the full parallel GPU+CPU set + single-stream per model (NUM_PARALLEL>1 blows the 8GB KV-cache) + long keep-alive (no cold-load thrash). Applied live via SSH container **recreate** — the node ollama is `docker run`, not compose, so env is immutable; procedure + Windows-cmd gotchas in KB #278809. Was 2/10m/2 live.)
- Warm model set: `qwen2.5:1.5b` GPU + `llama3.2:3b` GPU + `qwen2.5:7b` CPU
- Available: qwen2.5:7b, qwen2.5:1.5b, llama3.2:3b, mistral:7b, dolphin3:latest, gemma3:12b

### Starship-245 (100.64.0.6 / RTX 3050 4GB / 12GB RAM)
- Container: `archie_node_ollama` port 11434
- **MAX_LOADED_MODELS=4 | KEEP_ALIVE=60m | NUM_PARALLEL=1** (2026-07-06 — long keep-alive + single-stream; smaller than node-246 (4GB VRAM can't GPU-hold a 7B; 12GB RAM caps the set). Applied live via SSH recreate; KB #278809. Was 3/10m/2 live.)
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
