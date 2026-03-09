# Starship Agent Profiles + Model Catalog — Design Doc

**Date**: 2026-03-09
**Status**: Approved
**Related Projects**: #121 (Phase 1 Node Runtime), #122 (Phase 2), #123 (Phase 3)

---

## Overview

Enhance the Starship Agents tab to match Bridge Command's full agent profile system. Add a hub-curated model catalog with descriptions that integrates into model selection everywhere. Implement smart sync for agent edits. Optionally enable ComfyUI on GPU nodes for image/video generation.

## Decisions

- **Agent profiles**: Hybrid — reuse hub profile data (agent_emotional_state, identity, wellness, skills) via hub API. Node-local tracking planned for Phase 2 when jobs execute on nodes.
- **Model catalog**: Hub-curated descriptions (~40 models) + Ollama pull on nodes. Catalog enriches model dropdowns in both Bridge and Starship edit forms.
- **Agent editing**: Edit saves to hub immediately, auto-pushes if node online, queues if offline. Debounce batches rapid edits.
- **ComfyUI**: Optional 5th container on GPU nodes for image/video generation.

---

## Section 1: Bridge-Identical Agent Profile System

### Clickable Manifest Cards

Manifest cards (already built) become clickable. Clicking opens the same profile modal as Bridge Command.

- Click card → `openNodeAgentProfile(nodeAgentId)`
- Lookup `hub_agent_id` from `node_agents` table
- Fetch from hub: `GET /tools/bridge/api/agents/{hub_agent_id}/profile`
- Render with same `_renderFullProfile()` code (extracted/shared)

### Profile Modal Contents (same as Bridge)

1. Agent header: avatar, full name, codename, title, department, model, status
2. Bio
3. Station assignment
4. Performance (24h): tasks completed/failed, avg duration
5. Wellness: mood, stress level, energy level, mood intensity
6. Identity traits: key-value pairs
7. Voice DNA: engine, language, profile
8. Emotional history: last 10 mood entries
9. Rest cycles: last 5 entries
10. Skills: proficiency levels 1-5

### Footer Buttons

- **Edit** → opens agent edit form
- **Personnel File** → links to full agent view
- **Close**
- No Delete (use REMOVE on card instead)

### Edit Form (matches Bridge)

- Identity: codename, first/last name, title
- Model: dropdown with catalog descriptions (see Section 2)
  - Grouped by: installed on node / not installed
  - Each entry: name + size + one-line description + tier badge
  - "NOT INSTALLED" warning with inline PULL option
- System prompt, bio, worker_type
- Save → updates `node_agents` → auto-sync (see Section 3)

---

## Section 2: Hub-Curated Model Catalog

### Database: `model_catalog` table

```sql
CREATE TABLE model_catalog (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    family VARCHAR(50),
    parameter_size VARCHAR(20),
    size_gb NUMERIC(5,1),
    tier VARCHAR(20),        -- small, medium, large, xl
    category VARCHAR(50),    -- coding, general, creative, vision, reasoning, embedding
    description TEXT,
    use_cases TEXT,
    recommended_for TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Pre-populated catalog (~40 models)

**Coding**: deepseek-coder-v2:16b, codellama:latest, starcoder2:7b, qwen2.5-coder:7b
**General**: mistral:latest, llama3.1:8b, gemma2:9b, phi4:14b, qwen2.5:7b, command-r:latest
**Creative**: mixtral:8x7b, nous-hermes2:latest, dolphin3:latest
**Vision**: llava:latest, minicpm-v:8b, qwen2.5vl:7b
**Reasoning**: deepseek-r1:7b, deepseek-r1:1.5b
**Embedding**: nomic-embed-text, arctic-embed
**Small/Edge**: qwen2.5:0.5b, gemma2:2b, phi3.5:3.8b, smollm2:1.7b, llama3.2:1b
**Large**: yi:34b, deepseek-coder:33b, qwen2.5:32b, mixtral:8x7b

Each with human-written descriptions, e.g.:
> "DeepSeek Coder V2 (16B) — Excellent code generation and review. Strong at Python, JS, and system design. Good balance of quality and speed."

### Three Integration Points

1. **Starship Models tab** — browsable library grid
   - Cards: name, size, tier badge, category, description
   - Filter by category
   - PULL button → writes `model_pull` to `mesh_sync_log` → node runs `ollama pull`
   - INSTALLED badge for models already on node
   - Progress indicator during pull

2. **Starship Agent Edit → Model dropdown**
   - Grouped by installed / not-installed on node
   - Each entry: name + size + description line + tier badge
   - NOT INSTALLED entries show inline PULL option

3. **Bridge Agent Edit → Model dropdown**
   - Same enrichment: description line under each model name
   - Existing GPU/CPU grouping preserved
   - Catalog description adds context for model selection

### Hub endpoint

`GET /tools/starship/api/model-catalog` — returns full catalog
`GET /tools/bridge/api/model-catalog` — same data, for Bridge edit form

---

## Section 3: Smart Sync — Edit + Auto-Push

### Flow

1. User edits agent in Starship → `PUT /tools/starship/api/nodes/{id}/agents/{agent_id}`
2. Hub saves to `node_agents`, increments `config_version`
3. Hub writes/updates `agent_config` entry in `mesh_sync_log`
4. Node online (heartbeat < 60s) → response: `"sync": "sent"`
5. Node offline → response: `"sync": "queued"`
6. Node picks up on next `poll_syncs()` (every 60s)
7. Node ACK includes config_version applied

### Debounce

5-second window: if an unacknowledged `agent_config` sync already exists for this node, update its payload instead of creating a new row. Prevents sync spam from rapid edits.

### Sync Status Indicator (replaces PUSH button)

- Green: "All synced" (0 pending, versions match)
- Yellow: "2 changes pending" (node offline or hasn't polled)
- Blue spinner: "Syncing..." (waiting for ACK)
- Polls every 30s when Agents tab is active

### Database changes

```sql
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS hub_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS config_version INTEGER DEFAULT 1;
```

---

## Section 4: ComfyUI on GPU Nodes

### Optional 5th Container

Nodes with NVIDIA GPUs can run ComfyUI for image/video generation.

```yaml
  comfyui:
    image: comfyanonymous/comfyui:latest
    container_name: archie_starship_comfyui
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - comfyui_data:/app/models
    ports:
      - "${COMFYUI_PORT:-8188}:8188"
    networks:
      - starship_net
```

### Deploy Script Integration

- GPU detected → prompt: "Enable image generation? (Y/n)"
- Yes → adds ComfyUI service to docker-compose.yml
- No → skips (CPU-only node)

### Agent Integration

- One node agent assigned as image/video gen agent (like Pixel on hub)
- `gpu_tools` array on agent: `[{provider: "comfyui", type: "image_generation"}]`
- Agent card shows GPU tool row (same CSS as Bridge: provider + model + IMG/VID badge)

### Heartbeat

- Node reports `comfyui_available: true` + port in heartbeat
- Hub can dispatch image gen jobs via mesh sync `job_request`

### VRAM Sharing

- Same pattern as hub: ComfyUI needs VRAM → Ollama models unload first
- node_sync coordinates: check Ollama loaded models before ComfyUI job

### Checkpoint Management

- Ships with no checkpoints (saves download time)
- Model catalog includes "ComfyUI Checkpoints" category
- Node operator pulls from catalog (SDXL, SD1.5, etc.)
- Stored in `comfyui_data` Docker volume

---

## Files to Create/Modify

### New files
- `database/migrations/144_model_catalog.sql` — catalog table + seed data
- `database/migrations/145_node_agents_hub_link.sql` — hub_agent_id + config_version columns

### Modify
- `platform_v2/tools/starship/routes.py` — catalog endpoint, agent edit endpoint, smart sync
- `platform_v2/tools/starship/templates/tools/starship/starship.html` — profile modal, edit form, model library, sync indicator
- `platform_v2/tools/bridge/routes.py` — catalog endpoint for Bridge edit form
- `platform_v2/templates/tools/bridge.html` — enrich model dropdown with catalog descriptions
- `node_client/docker-compose.node.yml` — optional ComfyUI service
- `node_client/deploy-node.ps1` — ComfyUI prompt for GPU nodes
- `node_client/node_sync.py` — `model_pull` handler, VRAM coordination
