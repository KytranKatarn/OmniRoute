# Starship Agent Profiles + Model Catalog Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Bridge-identical agent profiles, a hub-curated model catalog, smart sync, and optional ComfyUI to Starship nodes.

**Architecture:** Hub `model_catalog` table seeds ~40 models with descriptions. Starship agents tab gets clickable profile modals + edit forms reusing Bridge patterns. Agent edits auto-sync to nodes via mesh_sync_log with debounce. Model catalog enriches dropdowns in both Bridge and Starship. Optional ComfyUI container on GPU nodes.

**Tech Stack:** Python/Flask, PostgreSQL, JavaScript (vanilla), Docker Compose, Ollama API

**Design Doc:** `docs/plans/2026-03-09-starship-agent-profiles-model-catalog-design.md`

---

## Task 1: Migration — model_catalog table + seed data

**Files:**
- Create: `database/migrations/144_model_catalog.sql`

**Step 1: Create migration with table + seed data**

Create `database/migrations/144_model_catalog.sql`:

```sql
-- Model catalog: hub-curated library with descriptions
CREATE TABLE IF NOT EXISTS model_catalog (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    family VARCHAR(50),
    parameter_size VARCHAR(20),
    size_gb NUMERIC(5,1),
    tier VARCHAR(20) CHECK (tier IN ('small', 'medium', 'large', 'xl')),
    category VARCHAR(50) CHECK (category IN ('coding', 'general', 'creative', 'vision', 'reasoning', 'embedding', 'small')),
    description TEXT,
    use_cases TEXT,
    recommended_for TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed ~40 curated models
INSERT INTO model_catalog (model_name, display_name, family, parameter_size, size_gb, tier, category, description, use_cases, recommended_for) VALUES
-- CODING
('deepseek-coder-v2:16b', 'DeepSeek Coder V2', 'deepseek', '16B', 9.4, 'large', 'coding',
 'Excellent code generation and review. Strong at Python, JS, and system design. Good balance of quality and speed.',
 'code generation, code review, debugging, refactoring',
 'Engineering station agents, code-heavy workflows'),
('codellama:latest', 'Code Llama', 'llama', '7B', 3.8, 'medium', 'coding',
 'Meta''s code-specialized LLM. Good at code completion, infilling, and following instructions about code.',
 'code completion, code infilling, code instructions',
 'Lightweight coding tasks, pair programming'),
('starcoder2:7b', 'StarCoder2', 'starcoder', '7B', 4.0, 'medium', 'coding',
 'Trained on The Stack v2. Strong multi-language support with 619 programming languages.',
 'multi-language code generation, code completion',
 'Polyglot coding agents, diverse language support'),
('qwen2.5-coder:7b', 'Qwen 2.5 Coder', 'qwen', '7B', 4.7, 'medium', 'coding',
 'Alibaba''s code specialist. Excellent at code generation, math reasoning, and following complex instructions.',
 'code generation, math reasoning, structured output',
 'Engineering agents needing math + code'),
('deepseek-coder:33b', 'DeepSeek Coder 33B', 'deepseek', '33B', 19.0, 'xl', 'coding',
 'Large code model with exceptional quality. Best for complex architectural decisions and large refactors.',
 'architecture design, complex refactoring, code analysis',
 'Senior engineering agents, architecture review'),
('deepseek-coder:latest', 'DeepSeek Coder 7B', 'deepseek', '7B', 3.8, 'medium', 'coding',
 'Compact code model with solid performance. Fast inference for routine coding tasks.',
 'code completion, quick fixes, routine generation',
 'Fast-turnaround coding tasks'),

-- GENERAL
('mistral:latest', 'Mistral 7B', 'mistral', '7B', 4.1, 'medium', 'general',
 'Excellent general-purpose model. Fast, reliable, and versatile. Great default choice for most tasks.',
 'general chat, summarization, analysis, writing',
 'Default agent model, versatile workloads'),
('llama3.1:8b', 'Llama 3.1 8B', 'llama', '8B', 4.9, 'medium', 'general',
 'Meta''s latest open model. Strong instruction following, multilingual, and tool use capabilities.',
 'general reasoning, tool use, multilingual tasks',
 'Agents needing tool use or multilingual support'),
('llama3:latest', 'Llama 3 8B', 'llama', '8B', 4.7, 'medium', 'general',
 'Previous generation Llama. Still solid for general tasks with good speed.',
 'general chat, basic reasoning, summarization',
 'Lightweight general-purpose agents'),
('gemma2:9b', 'Gemma 2 9B', 'google', '9B', 5.4, 'medium', 'general',
 'Google''s efficient model. Punches above its weight on benchmarks. Good at reasoning and instruction following.',
 'reasoning, analysis, instruction following',
 'Analytical agents, research tasks'),
('phi4:14b', 'Phi-4 14B', 'microsoft', '14B', 9.1, 'large', 'general',
 'Microsoft''s compact powerhouse. Excellent reasoning despite smaller size. Strong at STEM tasks.',
 'STEM reasoning, math, logic, analysis',
 'Research and analytics agents'),
('qwen2.5:7b', 'Qwen 2.5 7B', 'qwen', '7B', 4.7, 'medium', 'general',
 'Alibaba''s latest general model. Excellent multilingual support (29 languages). Strong at structured output.',
 'multilingual tasks, structured output, general reasoning',
 'Multilingual agents, i18n workflows'),
('command-r:latest', 'Command-R', 'cohere', '35B', 20.0, 'xl', 'general',
 'Cohere''s RAG-optimized model. Excellent at retrieval-augmented generation and tool use.',
 'RAG, tool use, knowledge synthesis, long context',
 'Knowledge-heavy agents, research workflows'),
('nous-hermes2:latest', 'Nous Hermes 2', 'nous', '7B', 4.1, 'medium', 'general',
 'Community fine-tune with strong instruction following. Creative and detailed responses.',
 'creative writing, detailed analysis, roleplay',
 'Creative and communications agents'),

-- CREATIVE
('mixtral:8x7b', 'Mixtral 8x7B', 'mistral', '8x7B', 26.0, 'xl', 'creative',
 'Mixture-of-experts architecture. Excellent at creative writing, nuanced analysis, and complex reasoning.',
 'creative writing, nuanced analysis, brainstorming',
 'Creative station agents, content generation'),
('dolphin3:latest', 'Dolphin 3', 'dolphin', '8B', 4.9, 'medium', 'creative',
 'Uncensored model based on Llama 3. Creative and unrestricted output for fiction and ideation.',
 'creative writing, fiction, brainstorming, ideation',
 'Creative agents needing unrestricted output'),
('aya:8b', 'Aya 8B', 'cohere', '8B', 4.9, 'medium', 'creative',
 'Cohere''s multilingual model. Excellent across 23 languages with cultural awareness.',
 'multilingual content, translation, cultural adaptation',
 'Diplomatic and communications agents'),

-- VISION
('llava:latest', 'LLaVA', 'llava', '7B', 4.7, 'medium', 'vision',
 'Large Language and Vision Assistant. Understands images and can describe, analyze, and answer questions about them.',
 'image analysis, visual QA, image description',
 'Agents needing image understanding'),
('minicpm-v:8b', 'MiniCPM-V', 'openbmb', '8B', 5.5, 'medium', 'vision',
 'Compact multimodal model. Good at OCR, document understanding, and visual reasoning.',
 'OCR, document analysis, visual reasoning',
 'Document processing agents'),
('qwen2.5vl:7b', 'Qwen 2.5 VL', 'qwen', '7B', 5.2, 'medium', 'vision',
 'Alibaba''s vision-language model. Strong at visual grounding, OCR, and video understanding.',
 'visual grounding, OCR, video understanding',
 'Visual analysis and media agents'),

-- REASONING
('deepseek-r1:7b', 'DeepSeek-R1 7B', 'deepseek', '7B', 4.7, 'medium', 'reasoning',
 'Reasoning-specialized model. Uses chain-of-thought for complex multi-step problems.',
 'math, logic puzzles, complex reasoning, planning',
 'Agents doing complex analysis or planning'),
('deepseek-r1:1.5b', 'DeepSeek-R1 1.5B', 'deepseek', '1.5B', 1.1, 'small', 'reasoning',
 'Compact reasoning model. Surprisingly capable at logical tasks despite small size.',
 'lightweight reasoning, logic, quick analysis',
 'Edge/small nodes needing reasoning capability'),

-- EMBEDDING
('nomic-embed-text', 'Nomic Embed Text', 'nomic', '137M', 0.3, 'small', 'embedding',
 'High-quality text embeddings. 8192 token context. Essential for semantic search and RAG.',
 'semantic search, RAG, similarity matching',
 'Required for knowledge base and search features'),

-- SMALL / EDGE
('qwen2.5:0.5b', 'Qwen 2.5 0.5B', 'qwen', '0.5B', 0.4, 'small', 'small',
 'Ultra-compact model. Fast classification and simple tasks. Minimal resource usage.',
 'classification, tagging, simple extraction',
 'Resource-constrained nodes, classification tasks'),
('gemma2:2b', 'Gemma 2 2B', 'google', '2B', 1.6, 'small', 'small',
 'Google''s tiny model. Good quality for its size. Quick responses for simple tasks.',
 'quick chat, simple tasks, edge deployment',
 'Low-resource nodes, fast-response agents'),
('phi3.5:3.8b', 'Phi 3.5', 'microsoft', '3.8B', 2.2, 'small', 'small',
 'Microsoft''s small model. Strong reasoning for its size. Good balance of capability and speed.',
 'reasoning, math, compact deployment',
 'Small nodes needing decent reasoning'),
('smollm2:1.7b', 'SmolLM2', 'huggingface', '1.7B', 1.0, 'small', 'small',
 'HuggingFace''s efficient small model. Fast inference, good for simple tasks.',
 'simple chat, text processing, edge tasks',
 'Minimal resource nodes'),
('llama3.2:3b', 'Llama 3.2 3B', 'llama', '3B', 2.0, 'small', 'small',
 'Meta''s compact Llama. Good instruction following in a small package.',
 'mobile/edge, simple instructions, quick tasks',
 'Small nodes, quick-turnaround agents'),
('llama3.2:1b', 'Llama 3.2 1B', 'llama', '1B', 0.7, 'small', 'small',
 'Tiniest Llama. Ultra-fast responses for basic tasks.',
 'classification, routing, basic chat',
 'Routing/classification agents'),

-- LARGE
('yi:34b', 'Yi 34B', 'yi', '34B', 19.0, 'xl', 'general',
 '01.AI''s large model. Excellent at complex reasoning, long documents, and nuanced analysis.',
 'complex reasoning, long documents, detailed analysis',
 'Research agents, deep analysis tasks'),
('qwen2.5:14b', 'Qwen 2.5 14B', 'qwen', '14B', 9.0, 'large', 'general',
 'Mid-size Qwen with excellent quality. Good step up from 7B for demanding tasks.',
 'complex tasks, quality-critical generation',
 'Agents needing higher quality than 7B models'),
('gemma2:27b', 'Gemma 2 27B', 'google', '27B', 16.0, 'large', 'general',
 'Google''s largest open Gemma. Strong across benchmarks, competitive with much larger models.',
 'complex reasoning, quality writing, analysis',
 'Premium agents, quality-critical tasks'),
('qwen2.5:32b', 'Qwen 2.5 32B', 'qwen', '32B', 20.0, 'xl', 'general',
 'Large Qwen model. Excellent for complex tasks requiring deep understanding.',
 'complex reasoning, long-form generation, analysis',
 'High-capability agents on powerful nodes')
ON CONFLICT (model_name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    family = EXCLUDED.family,
    parameter_size = EXCLUDED.parameter_size,
    size_gb = EXCLUDED.size_gb,
    tier = EXCLUDED.tier,
    category = EXCLUDED.category,
    description = EXCLUDED.description,
    use_cases = EXCLUDED.use_cases,
    recommended_for = EXCLUDED.recommended_for;
```

**Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -c "$(cat database/migrations/144_model_catalog.sql)"
```

**Step 3: Commit**

```bash
git add database/migrations/144_model_catalog.sql
git commit -m "feat(starship): add model_catalog table with 35 curated models"
```

---

## Task 2: Migration — node_agents hub_agent_id + config_version

**Files:**
- Create: `database/migrations/145_node_agents_hub_link.sql`

**Step 1: Create migration**

```sql
-- Link node_agents to hub agents table + version tracking for smart sync
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS hub_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS config_version INTEGER DEFAULT 1;

-- Backfill hub_agent_id for existing node_agents by matching name
UPDATE node_agents na
SET hub_agent_id = a.id
FROM agents a
WHERE na.name = a.name AND na.hub_agent_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_node_agents_hub_agent ON node_agents(hub_agent_id);
```

**Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /migrations/145_node_agents_hub_link.sql
# Fallback if path doesn't work:
docker exec archie_database psql -U archie -d archie -c "$(cat database/migrations/145_node_agents_hub_link.sql)"
```

**Step 3: Commit**

```bash
git add database/migrations/145_node_agents_hub_link.sql
git commit -m "feat(starship): add hub_agent_id + config_version to node_agents"
```

---

## Task 3: Model catalog API endpoint

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` (after line ~890)
- Modify: `platform_v2/tools/bridge/routes.py` (after line ~6733)

**Step 1: Add catalog endpoint to Starship routes**

Add after `api_node_crew_manifest()` (~line 890):

```python
@starship_bp.route("/api/model-catalog")
@login_required
def api_model_catalog():
    """Return the curated model catalog for browsing and selection."""
    category = request.args.get("category")
    with get_db_cursor() as (conn, cur):
        if category:
            cur.execute(
                "SELECT * FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb",
                (category,),
            )
        else:
            cur.execute(
                "SELECT * FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
            )
        models = cur.fetchall()
        return jsonify({"success": True, "models": [dict(m) for m in models]})
```

**Step 2: Add catalog endpoint to Bridge routes**

Add near `get_agent_form_context()` (~line 6733):

```python
@bridge_bp.route("/api/model-catalog")
@login_required
def api_model_catalog():
    """Return model catalog for enriched model dropdowns."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT model_name, display_name, description, tier, category, size_gb, parameter_size "
            "FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
        )
        models = cur.fetchall()
        catalog = {m["model_name"]: dict(m) for m in models}
        return jsonify({"success": True, "catalog": catalog})
```

**Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/bridge/routes.py
git commit -m "feat(starship): add model catalog API endpoints for Starship + Bridge"
```

---

## Task 4: Model Library UI in Starship Models tab

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` (Models tab at line ~624, JS section)

**Step 1: Add Model Library section to Models tab HTML**

After the existing `#d-models-grid` div (~line 630), add a "MODEL LIBRARY" section with category filter buttons and a card grid.

**Step 2: Add renderModelLibrary() JavaScript**

Add function that fetches `/tools/starship/api/model-catalog`, renders cards with: display_name, size badge, tier badge, category, description, use_cases. Each card has PULL button (or INSTALLED badge if model already on node). PULL calls `POST /tools/starship/api/nodes/{nodeDbId}/pull-model`.

**Step 3: Add pull-model endpoint to routes.py**

Writes `model_pull` sync command to `mesh_sync_log` with `{model_name: "..."}` payload.

**Step 4: Add model_pull handler to node_sync.py**

In `handle_sync()` handlers dict (~line 524), add `"model_pull": _handle_model_pull`. Handler runs `ollama pull <model>` via subprocess inside Docker container.

**Step 5: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html node_client/node_sync.py
git commit -m "feat(starship): model library UI with PULL + node handler"
```

---

## Task 5: Clickable agent cards + hub profile modal

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` (lines ~1114-1243 _renderStarshipAgentCard, and new modal HTML)
- Modify: `platform_v2/tools/starship/routes.py`

**Step 1: Add profile modal HTML to starship.html**

Add a modal matching Bridge's `agent-profile-modal` structure (bridge.html:9146-9187). Use same IDs/classes so we can reuse rendering JS. Include sections for: header, bio, station, performance, wellness, identity traits, emotional history, rest cycles, skills.

**Step 2: Add node agent profile endpoint**

In starship routes.py, add:
```python
@starship_bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>/profile")
@login_required
def api_node_agent_profile(node_id, agent_id):
    """Get full agent profile — proxies to hub agent via hub_agent_id."""
```
This reads `hub_agent_id` from `node_agents`, then queries the same tables as Bridge's `agent_profile()` (routes.py:8742): agents, agent_emotional_state, agent_identity, agent_skills, task_execution_log, agent_rest_cycles, agent_memory.

**Step 3: Make cards clickable**

In `_renderStarshipAgentCard()` (~line 1114), add `card.style.cursor = 'pointer'` and `card.onclick = function() { openNodeAgentProfile(agent.agent_id); }`.

**Step 4: Add openNodeAgentProfile() and renderNodeAgentProfile() JS**

Fetches profile data, renders into the modal using the same structure as Bridge's `_renderFullProfile()` (bridge.html:18252). Adapted for Starship context (no load/unload toggle, no fleet mode).

**Step 5: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): clickable agent cards with full hub profile modal"
```

---

## Task 6: Agent edit form in Starship

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html`
- Modify: `platform_v2/tools/starship/routes.py`

**Step 1: Add agent edit form modal HTML**

Match Bridge's `agent-form-modal` (bridge.html:9190-9300). Fields: codename, first/last name, title, model dropdown (enriched with catalog descriptions + installed status), system_prompt, bio, worker_type.

**Step 2: Add node agent form context endpoint**

```python
@starship_bp.route("/api/nodes/<int:node_id>/agent-form-context")
@login_required
def api_node_agent_form_context(node_id):
    """Return models + catalog for agent edit form."""
```
Returns: node's installed models (from `node_ollama_models`), catalog data (from `model_catalog`), station list.

**Step 3: Add node agent update endpoint**

```python
@starship_bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>", methods=["PUT"])
@login_required
def api_update_node_agent(node_id, agent_id):
    """Update a node agent and trigger smart sync."""
```
Saves to `node_agents`, increments `config_version`, writes/updates `agent_config` to `mesh_sync_log` with 5s debounce (check for existing unack'd sync).

**Step 4: Add enriched model dropdown JS**

`_populateNodeModelDropdown(models, catalog, currentModel)` — groups by installed/not-installed, each entry shows name + size + catalog description + tier badge. Not-installed entries show "(PULL REQUIRED)" label.

**Step 5: Wire edit button in profile modal**

Profile footer "Edit" button → closes profile → opens edit form pre-populated with current data.

**Step 6: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): agent edit form with catalog-enriched model dropdown"
```

---

## Task 7: Smart sync indicator

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` (sync-indicator at line ~617)
- Modify: `platform_v2/tools/starship/routes.py`

**Step 1: Add sync status endpoint**

```python
@starship_bp.route("/api/nodes/<int:node_id>/sync-status")
@login_required
def api_node_sync_status(node_id):
    """Return pending sync count and last ACK'd config_version."""
```
Queries `mesh_sync_log` for pending (status='sent') entries for this node + latest `config_version` from `node_agents`.

**Step 2: Replace PUSH button with sync indicator**

Replace the existing `pushAgentConfig()` button area with a status display that auto-polls every 30s:
- Green dot + "All synced"
- Yellow dot + "N changes pending"
- Blue spinner + "Syncing..."

Keep a manual "Force Sync" button for edge cases.

**Step 3: Auto-trigger sync on agent edit save**

After successful PUT to update agent, the response includes sync status. UI updates indicator immediately.

**Step 4: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): smart sync indicator with auto-push and status polling"
```

---

## Task 8: Enrich Bridge model dropdown with catalog descriptions

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (model dropdown at line ~9254, rendering at ~18935)

**Step 1: Fetch catalog in agent form context**

In `openAgentForm()` or wherever the form loads, also fetch `GET /tools/bridge/api/model-catalog`. Store as `window._modelCatalog`.

**Step 2: Enrich model dropdown entries**

In the model dropdown rendering code (~line 18935), after creating each model option element, look up `_modelCatalog[modelName]` and append the description as a subtitle line under the model name.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): enrich model dropdown with catalog descriptions"
```

---

## Task 9: Optional ComfyUI container for GPU nodes

**Files:**
- Modify: `node_client/deploy-node.ps1`
- Modify: `node_client/docker-compose.node.yml`
- Modify: `node_client/node_sync.py`

**Step 1: Add ComfyUI service to docker-compose.node.yml (commented out)**

Add a `comfyui` service block after `node_api`, commented out by default. The deploy script uncomments it when GPU is detected and user opts in.

**Step 2: Update deploy-node.ps1**

After GPU detection, prompt: "Enable image generation with ComfyUI? (Y/n)". If yes, uncomment the comfyui service in docker-compose.yml and add `comfyui_data` volume.

**Step 3: Add ComfyUI entries to model_catalog**

Add ~5 checkpoint entries with category 'comfyui':
- SDXL Base, SD 1.5, Juggernaut XL, DreamShaper, etc.

**Step 4: Add gpu_tools support to node agent manifest**

In `api_node_crew_manifest()`, check if an agent has `gpu_tools` in its config. If so, include in the manifest response for card rendering.

**Step 5: Commit**

```bash
git add node_client/deploy-node.ps1 node_client/docker-compose.node.yml node_client/node_sync.py database/migrations/144_model_catalog.sql
git commit -m "feat(starship): optional ComfyUI container for GPU nodes"
```

---

## Task 10: Deploy + Integration Test

**Step 1: Deploy to hub**

```bash
docker compose restart archie_platform
```

**Step 2: Test model catalog**

1. Go to Starship Command → Models tab → verify Model Library section renders
2. Check category filters work
3. Verify INSTALLED badges show for models on KYTRAN-StarShip

**Step 3: Test agent profile**

1. Agents tab → click an agent card → verify profile modal opens
2. Check wellness, identity, performance sections populated
3. Click Edit → verify form opens with current data
4. Change a field → Save → verify sync indicator updates

**Step 4: Test Bridge enrichment**

1. Bridge Command → Crew → click agent → Edit
2. Verify model dropdown shows catalog descriptions

**Step 5: Complete Dev HQ tasks**

```
mcp complete_task (Tasks 826-835)
mcp update_project_understanding (Project 124)
mcp log_decision "Agent profiles + model catalog: hub profiles for Starship, curated 35-model catalog, smart sync with debounce"
```

**Step 6: Commit + Push**

```bash
git push origin main
```
