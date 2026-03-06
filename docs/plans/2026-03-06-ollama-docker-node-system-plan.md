# Ollama Containerization & Node System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Containerize Ollama in Docker, register Archie as starbase node, build starship Docker package for compute donor nodes, add Tier 6 node routing to smart router, and build Starship Command UI.

**Architecture:** Ollama moves from systemd to a Docker container (`archie_ollama`) on `archie_network`, sharing GPU with ComfyUI. All AI bridge integration points already read from env vars — no code changes for the migration. Starship nodes are lightweight Docker packages (Ollama + sidecar) that register with Archie and share compute. The existing `remote_nodes` table, `node_ollama_models`, and `node_client/` package provide the foundation.

**Tech Stack:** Docker Compose, Ollama Docker image, Python 3.11 (sidecar), Flask (platform), PostgreSQL (existing), LCARS HTML/CSS/JS (UI)

**Design doc:** `docs/plans/2026-03-06-ollama-docker-node-system-design.md`

---

## Task 1: Containerize Archie's Ollama (URGENT — fixes 500 errors)

**Files:**
- Modify: `docker-compose.yml` (add archie_ollama service after line 131)
- Modify: `.env:30-33` (update OLLAMA_PRIMARY, OLLAMA_HOST)
- Modify: `platform_v2/.env:30-33` (same updates)
- Modify: `docker-compose.yml:55-63` (update OLLAMA_PRIMARY ref, OLLAMA_MODELS, remove old volume mount)

**Step 1: Add archie_ollama service to docker-compose.yml**

Insert before the `# n8n Workflow Automation` comment (line 132):

```yaml
  # Ollama LLM Engine (models on Samsung 840 SSD)
  archie_ollama:
    image: ollama/ollama:latest
    container_name: archie_ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - OLLAMA_KEEP_ALIVE=24h
      - OLLAMA_MAX_LOADED_MODELS=13
      - OLLAMA_NUM_PARALLEL=4
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - /mnt/llm_drive/ollama:/root/.ollama
    ports:
      - "192.168.1.200:11434:11434"
    networks:
      - archie_internal
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

**Step 2: Update .env files (both root and platform_v2)**

In both `.env` and `platform_v2/.env`, change:

```
# OLD
OLLAMA_PRIMARY=host.docker.internal:11434
OLLAMA_HOST=http://host.docker.internal:11434

# NEW
OLLAMA_PRIMARY=archie_ollama:11434
OLLAMA_HOST=http://archie_ollama:11434
```

**Step 3: Update archie_platform env in docker-compose.yml**

In the `archie_platform` service environment section:
- Change `OLLAMA_MODELS: /mnt/data2/ollama/models` to `OLLAMA_MODELS: /mnt/llm_drive/ollama/models`
- Remove the old volume mount `- /mnt/data2/ollama/models:/mnt/data2/ollama/models:ro` (line 112)
- Add new volume mount `- /mnt/llm_drive/ollama/models:/mnt/llm_drive/ollama/models:ro`
- Add `archie_ollama` to `depends_on`

**Step 4: Stop and disable systemd Ollama**

```bash
sudo systemctl stop ollama
sudo systemctl disable ollama
```

**Step 5: Start the Ollama container**

```bash
docker compose up -d archie_ollama
sleep 10
curl -s http://192.168.1.200:11434/api/tags | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"models\"])} models found')"
```

Expected: `18 models found`

**Step 6: Restart platform with new env**

```bash
docker compose up -d archie_platform
sleep 15
curl -s http://192.168.1.200:3000/health
```

Expected: `200 OK`

**Step 7: Verify AI bridge integration**

```bash
# Test inference through platform
curl -s http://192.168.1.200:11434/api/generate -d '{"model":"smollm2:1.7b","prompt":"Say hello","stream":false}' | python3 -c "import json,sys; print(json.load(sys.stdin).get('response','FAIL')[:50])"

# Check container-to-container connectivity
docker exec archie_platform curl -s http://archie_ollama:11434/api/tags | python3 -c "import json,sys; print(f'{len(json.load(sys.stdin)[\"models\"])} models visible from platform')"
```

Expected: Response text + `18 models visible from platform`

**Step 8: Commit**

```bash
git add docker-compose.yml .env platform_v2/.env
git commit -m "feat: containerize Ollama — systemd to Docker on LLM SSD"
```

---

## Task 2: Register Archie as Starbase Node

**Files:**
- Create: `database/migrations/081_register_starbase_node.sql`

**Step 1: Write migration SQL**

```sql
-- 081: Register Archie main server as starbase node
-- Idempotent: ON CONFLICT DO UPDATE

INSERT INTO remote_nodes (
    node_id, node_name, description, hostname, port,
    status, is_active, approval_status,
    deployment_mode, bridge_enabled, bridge_priority,
    gpu_available, gpu_model, gpu_vram_gb,
    cpu_model, cpu_cores, ram_gb, disk_gb,
    ollama_available, comfyui_available, docker_available,
    nvidia_docker, docker_version, iaae_compliant,
    os_info, region, timezone
) VALUES (
    'archie-starbase',
    'Archie Starbase',
    'Primary A.R.C.H.I.E. server — hosts platform, database, all modules',
    '192.168.1.200',
    11434,
    'online',
    true,
    'approved',
    'starbase',
    true,
    100,
    true,
    'NVIDIA Quadro M4000',
    8.0,
    'Intel Xeon E5-2658 v2',
    20,
    128.0,
    110.0,
    true,
    true,
    true,
    true,
    '27.5.1',
    true,
    'Ubuntu 24.04 LTS',
    'local',
    'America/Toronto'
) ON CONFLICT (node_id) DO UPDATE SET
    node_name = EXCLUDED.node_name,
    hostname = EXCLUDED.hostname,
    deployment_mode = EXCLUDED.deployment_mode,
    bridge_enabled = EXCLUDED.bridge_enabled,
    bridge_priority = EXCLUDED.bridge_priority,
    status = EXCLUDED.status,
    is_active = EXCLUDED.is_active,
    approval_status = EXCLUDED.approval_status,
    updated_at = NOW();
```

**Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/081_register_starbase_node.sql
```

Note: Mount the migration file first or copy it in. Alternative:

```bash
cat database/migrations/081_register_starbase_node.sql | docker exec -i archie_database psql -U archie -d archie
```

**Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT node_id, node_name, deployment_mode, bridge_enabled, bridge_priority, status FROM remote_nodes WHERE node_id='archie-starbase';"
```

Expected: One row with `starbase | true | 100 | online`

**Step 4: Sync starbase models to node_ollama_models**

```sql
-- Populate node_ollama_models for starbase from live Ollama
-- This will be done via a Python script that calls /api/tags and inserts
```

Create a one-time sync script:

```bash
docker exec archie_platform python3 -c "
import json, urllib.request
from database import get_db_cursor

resp = urllib.request.urlopen('http://archie_ollama:11434/api/tags')
models = json.loads(resp.read())['models']

with get_db_cursor(commit=True) as (conn, cur):
    for m in models:
        cur.execute('''
            INSERT INTO node_ollama_models (node_id, model_name, model_size_gb, is_available)
            VALUES ('archie-starbase', %s, %s, true)
            ON CONFLICT (node_id, model_name) DO UPDATE SET
                model_size_gb = EXCLUDED.model_size_gb,
                is_available = true
        ''', (m['name'], round(m['size'] / (1024**3), 2)))
    print(f'Synced {len(models)} models for starbase')
"
```

**Step 5: Commit**

```bash
git add database/migrations/081_register_starbase_node.sql
git commit -m "feat: register Archie as starbase node in remote_nodes"
```

---

## Task 3: Update Starship Docker Package

**Files:**
- Modify: `node_client/docker-compose.node.yml` (replace with starship-focused version)
- Modify: `node_client/node_sync.py` (update heartbeat to include Ollama model list)
- Modify: `node_client/config.example.json` (add deployment_mode field)

**Step 1: Rewrite docker-compose to starship model**

Replace `node_client/docker-compose.node.yml` with a 2-service stack (remove node_database and node_platform — starships don't run the platform):

```yaml
###############################################################################
# A.R.C.H.I.E. Starship Node - Docker Compose
# ============================================================================
# 2-service stack: Ollama LLM engine + sync/heartbeat agent
# The starship contributes compute back to the Archie Starbase.
# Users access Archie's platform directly — no local UI.
#
# Required env vars (set in .env):
#   NODE_ID, HUB_URL, HUB_API_KEY
###############################################################################

services:
  ollama:
    image: ollama/ollama:latest
    container_name: archie_starship_ollama
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - OLLAMA_KEEP_ALIVE=24h
      - OLLAMA_NUM_PARALLEL=4
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "${OLLAMA_PORT:-11434}:11434"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - starship_net

  sync:
    image: python:3.11-slim
    container_name: archie_starship_sync
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      NODE_ID: ${NODE_ID}
      HUB_URL: ${HUB_URL}
      HUB_API_KEY: ${HUB_API_KEY}
      OLLAMA_HOST: http://ollama:11434
      HEARTBEAT_INTERVAL: "30"
      DEPLOYMENT_MODE: "starship"
    volumes:
      - ./node_sync.py:/app/node_sync.py:ro
    working_dir: /app
    command: ["python3", "-u", "node_sync.py"]
    networks:
      - starship_net

volumes:
  ollama_data:

networks:
  starship_net:
    driver: bridge
```

**Step 2: Update node_sync.py heartbeat to report Ollama models**

In the heartbeat function, add Ollama model discovery:

```python
def get_ollama_status():
    """Query local Ollama for loaded and available models."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://ollama:11434")
    result = {"loaded_models": [], "available_models": []}
    try:
        # Available models
        tags = http_get(f"{ollama_host}/api/tags")
        if tags and "models" in tags:
            result["available_models"] = [
                {"name": m["name"], "size_gb": round(m["size"] / (1024**3), 2)}
                for m in tags["models"]
            ]
        # Currently loaded models
        ps = http_get(f"{ollama_host}/api/ps")
        if ps and "models" in ps:
            result["loaded_models"] = [m["name"] for m in ps["models"]]
    except Exception as e:
        logger.warning(f"Ollama status check failed: {e}")
    return result
```

Add `deployment_mode` to the heartbeat payload:

```python
payload["deployment_mode"] = os.getenv("DEPLOYMENT_MODE", "starship")
payload["ollama"] = get_ollama_status()
```

**Step 3: Update config.example.json**

```json
{
  "node_id": "starship_xxxxxxxxxxxxxxxx",
  "api_key": "your-api-key-from-registration",
  "server_url": "http://192.168.1.200:3000",
  "heartbeat_interval": 30,
  "deployment_mode": "starship",
  "log_level": "INFO",
  "ollama_port": 11434
}
```

**Step 4: Commit**

```bash
git add node_client/
git commit -m "feat: update node client to starship model — Ollama container + sync sidecar"
```

---

## Task 4: Add Starship Tier to Smart Router

**Files:**
- Modify: `ai_bridge/smart_router.py` (add Tier 6 node routing)
- Modify: `ai_bridge/node_router.py` (enhance node selection logic)

**Step 1: Read current smart_router.py escalation logic**

Find the escalation chain in `smart_router.py`. The current tiers handle local models and cloud fallback. We insert starship node routing between local and cloud.

**Step 2: Add starship node check function**

Add to `smart_router.py` or enhance existing `node_router.py`:

```python
def get_available_starship_nodes(model_name):
    """
    Find active starship nodes that have the requested model available.
    Returns list of nodes sorted by priority (highest first), then load (lowest first).
    """
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT rn.node_id, rn.hostname, rn.port, rn.bridge_priority,
                   rn.current_load, rn.max_concurrent, nom.avg_response_ms
            FROM remote_nodes rn
            JOIN node_ollama_models nom ON nom.node_id = rn.node_id
            WHERE rn.is_active = true
              AND rn.bridge_enabled = true
              AND rn.approval_status = 'approved'
              AND rn.deployment_mode IN ('starship', 'starbase')
              AND rn.node_id != 'archie-starbase'
              AND rn.last_heartbeat > NOW() - INTERVAL '90 seconds'
              AND nom.model_name = %s
              AND nom.is_available = true
              AND rn.current_load < rn.max_concurrent
            ORDER BY rn.bridge_priority DESC, rn.current_load ASC,
                     nom.avg_response_ms ASC NULLS LAST
        """, (model_name,))
        return cur.fetchall()
```

**Step 3: Insert Tier 6 into escalation chain**

In the escalation logic, after local model checks fail and before cloud escalation:

```python
# Tier 6: Check starship nodes
starship_nodes = get_available_starship_nodes(model_name)
if starship_nodes:
    node = starship_nodes[0]  # Best available
    ollama_url = f"http://{node['hostname']}:{node['port']}"
    logger.info(f"Tier 6: Routing to starship node {node['node_id']} at {ollama_url}")
    return {
        "provider": "starship",
        "node_id": node["node_id"],
        "ollama_url": ollama_url,
        "model": model_name
    }
```

**Step 4: Update bridge_dispatcher.py to handle starship responses**

In the dispatch function, add handling for `provider == "starship"`:

```python
if route["provider"] == "starship":
    # Direct Ollama call to starship node
    response = call_ollama(
        route["ollama_url"],
        model=route["model"],
        prompt=prompt,
        timeout=timeout
    )
    # Log with node_id for tracking
    log_dispatch(agent_name, route["model"], route["node_id"], response)
    return response
```

**Step 5: Commit**

```bash
git add ai_bridge/smart_router.py ai_bridge/node_router.py ai_bridge/bridge_dispatcher.py
git commit -m "feat: add Tier 6 starship node routing to smart router"
```

---

## Task 5: Enhance Network Tab with Live Node Data

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` (add /api/nodes/{id}/models, /health, /dispatch-test endpoints)
- Modify: `platform_v2/tools/bridge/mesh_routes.py` (enhance heartbeat handler to store Ollama data)

**Step 1: Add node models endpoint**

In `routes.py`, add:

```python
@bridge_bp.route("/api/nodes/<node_id>/models")
@admin_required
def get_node_models(node_id):
    """Get live model list for a specific node."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT model_name, model_size_gb, is_available, avg_response_ms
            FROM node_ollama_models
            WHERE node_id = %s
            ORDER BY model_name
        """, (node_id,))
        models = cur.fetchall()
    return jsonify({"success": True, "models": models})
```

**Step 2: Add node health endpoint**

```python
@bridge_bp.route("/api/nodes/<node_id>/health")
@admin_required
def get_node_health(node_id):
    """Get latest heartbeat data for a specific node."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT payload, created_at
            FROM node_heartbeats
            WHERE node_id = (SELECT id FROM remote_nodes WHERE node_id = %s)
            ORDER BY created_at DESC LIMIT 1
        """, (node_id,))
        row = cur.fetchone()
    if not row:
        return jsonify({"success": False, "error": "No heartbeat data"}), 404
    return jsonify({"success": True, "health": row["payload"], "last_seen": str(row["created_at"])})
```

**Step 3: Add dispatch test endpoint**

```python
@bridge_bp.route("/api/nodes/<node_id>/dispatch-test", methods=["POST"])
@admin_required
def dispatch_test_to_node(node_id):
    """Send a test inference request to a specific node's Ollama."""
    import time
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT hostname, port FROM remote_nodes WHERE node_id = %s AND is_active = true", (node_id,))
        node = cur.fetchone()
    if not node:
        return jsonify({"success": False, "error": "Node not found or inactive"}), 404

    ollama_url = f"http://{node['hostname']}:{node['port']}"
    try:
        start = time.time()
        resp = requests.post(f"{ollama_url}/api/tags", timeout=10)
        latency_ms = round((time.time() - start) * 1000)
        models = resp.json().get("models", [])
        return jsonify({
            "success": True,
            "latency_ms": latency_ms,
            "model_count": len(models),
            "ollama_url": ollama_url
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 502
```

**Step 4: Update heartbeat handler to store Ollama model data**

In `mesh_routes.py`, when processing heartbeats that include `ollama` payload, sync to `node_ollama_models`:

```python
if "ollama" in heartbeat_data:
    ollama_data = heartbeat_data["ollama"]
    available = ollama_data.get("available_models", [])
    for model in available:
        cur.execute("""
            INSERT INTO node_ollama_models (node_id, model_name, model_size_gb, is_available)
            VALUES (%s, %s, %s, true)
            ON CONFLICT (node_id, model_name) DO UPDATE SET
                model_size_gb = EXCLUDED.model_size_gb,
                is_available = true
        """, (node_id, model["name"], model.get("size_gb", 0)))
    # Mark models no longer available
    available_names = [m["name"] for m in available]
    if available_names:
        cur.execute("""
            UPDATE node_ollama_models SET is_available = false
            WHERE node_id = %s AND model_name != ALL(%s)
        """, (node_id, available_names))
```

**Step 5: Commit**

```bash
git add platform_v2/tools/bridge/routes.py platform_v2/tools/bridge/mesh_routes.py
git commit -m "feat: enhance Network tab with live node models, health, and dispatch test"
```

---

## Task 6: Build Starship Command UI

**Files:**
- Create: `database/migrations/082_starship_command.sql` (add user_id to remote_nodes)
- Modify: `platform_v2/tools/bridge/routes.py` (add role detection to bridge view)
- Modify: `platform_v2/templates/tools/bridge.html` (add Starship Command panel)

**Step 1: Migration — add user_id to remote_nodes**

```sql
-- 082: Link remote_nodes to user accounts for Starship Command
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_remote_nodes_user_id ON remote_nodes(user_id);
```

**Step 2: Add role detection to bridge route**

In the main bridge view route, check if the logged-in user is a starship operator:

```python
# In the bridge index route
def get_bridge_context(user_id):
    """Determine if user is a starship operator."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT node_id, node_name, deployment_mode
            FROM remote_nodes
            WHERE user_id = %s AND deployment_mode = 'starship' AND is_active = true
        """, (user_id,))
        node = cur.fetchone()
    return node  # None = starbase admin, dict = starship operator
```

Pass `starship_node` to the template. In the template, conditionally render Starship Command vs Bridge Command.

**Step 3: Add Starship Command HTML panel**

In `bridge.html`, add a conditional block:

```html
{% if starship_node %}
<!-- STARSHIP COMMAND VIEW -->
<div class="starship-command" id="starship-command">
    <div class="bridge-header" style="--accent: #00e5ff;">
        <h1>STARSHIP COMMAND</h1>
        <span class="node-name">{{ starship_node.node_name }}</span>
    </div>

    <!-- 5 tabs: Status, Hardware, Models, Agents, Profile -->
    <div class="starship-tabs">
        <button class="starship-tab active" data-panel="sc-status">Status</button>
        <button class="starship-tab" data-panel="sc-hardware">Hardware</button>
        <button class="starship-tab" data-panel="sc-models">Models</button>
        <button class="starship-tab" data-panel="sc-agents">Agents</button>
        <button class="starship-tab" data-panel="sc-profile">Profile</button>
    </div>

    <!-- Tab panels -->
    <div id="sc-status" class="starship-panel active">
        <div class="sc-card">
            <h3>Connection Status</h3>
            <div id="sc-connection-status"></div>
            <div id="sc-uptime"></div>
            <div id="sc-last-heartbeat"></div>
        </div>
        <div class="sc-card">
            <h3>Contribution Stats</h3>
            <div id="sc-jobs-processed"></div>
        </div>
    </div>

    <div id="sc-hardware" class="starship-panel">
        <div id="sc-hardware-bars"></div>
    </div>

    <div id="sc-models" class="starship-panel">
        <div id="sc-models-grid"></div>
    </div>

    <div id="sc-agents" class="starship-panel">
        <div id="sc-agents-grid"></div>
    </div>

    <div id="sc-profile" class="starship-panel">
        <form id="sc-profile-form">
            <label>Display Name</label>
            <input type="text" id="sc-display-name" />
            <button type="submit">Save</button>
        </form>
        <div id="sc-recommendations"></div>
    </div>
</div>
{% else %}
<!-- BRIDGE COMMAND VIEW (existing) -->
...existing bridge HTML...
{% endif %}
```

**Step 4: Add Starship Command CSS**

Add to bridge styles or create `static/css/starship-command.css`:

```css
.starship-command {
    --accent: #00e5ff; /* Teal for starship */
}
.starship-tabs { display: flex; gap: 4px; margin: 16px 0; }
.starship-tab {
    background: rgba(0, 229, 255, 0.1);
    border: 1px solid rgba(0, 229, 255, 0.3);
    color: #00e5ff;
    padding: 8px 20px;
    cursor: pointer;
    font-family: 'Antonio', sans-serif;
    text-transform: uppercase;
}
.starship-tab.active {
    background: rgba(0, 229, 255, 0.25);
    border-color: #00e5ff;
}
.sc-card {
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(0, 229, 255, 0.2);
    border-radius: 8px;
    padding: 20px;
    margin: 12px 0;
}
```

**Step 5: Add Starship Command JavaScript**

Add JS to fetch node data and populate panels:

```javascript
async function loadStarshipData(nodeId) {
    const [health, models] = await Promise.all([
        api(`/tools/bridge/api/nodes/${nodeId}/health`),
        api(`/tools/bridge/api/nodes/${nodeId}/models`)
    ]);
    renderStarshipStatus(health);
    renderStarshipModels(models);
}
```

**Step 6: Commit**

```bash
git add database/migrations/082_starship_command.sql platform_v2/tools/bridge/routes.py platform_v2/templates/tools/bridge.html
git commit -m "feat: Starship Command UI — role-based bridge view for node operators"
```

---

## Task 7: Test with Windows Machine on LAN

**Step 1: On the Windows test machine, install Docker Desktop**

Ensure WSL2 backend is enabled and Docker is running.

**Step 2: Copy starship package**

Copy `node_client/` contents to the Windows machine. Create `.env`:

```env
NODE_ID=starship-windows-test
HUB_URL=http://192.168.1.200:3000
HUB_API_KEY=<generated-from-archie-registration>
OLLAMA_PORT=11434
```

**Step 3: Start the starship**

```bash
docker compose -f docker-compose.node.yml up -d
```

**Step 4: Approve in Bridge Network tab**

Go to http://192.168.1.200:3000/tools/bridge → Network tab → Pending nodes → Approve

**Step 5: Verify in Network tab**

- Node shows as `online` with hardware specs
- Models list populates after Archie assigns models
- Dispatch test returns successful ping

**Step 6: Test dispatch routing**

From Bridge dispatch, send a job that the starship can handle. Verify:
- Job routes to starship node (check bridge_jobs for node_id)
- Response comes back correctly
- Starship heartbeat shows updated load

---

## Summary — Commit Sequence

| # | Commit message | What it does |
|---|---------------|-------------|
| 1 | `feat: containerize Ollama — systemd to Docker on LLM SSD` | Fixes 500 errors, adds archie_ollama container |
| 2 | `feat: register Archie as starbase node in remote_nodes` | Node Zero in the fleet |
| 3 | `feat: update node client to starship model — Ollama container + sync sidecar` | Starship Docker package |
| 4 | `feat: add Tier 6 starship node routing to smart router` | Fleet-wide dispatch |
| 5 | `feat: enhance Network tab with live node models, health, and dispatch test` | Network tab endpoints |
| 6 | `feat: Starship Command UI — role-based bridge view for node operators` | Starship user experience |
| 7 | (manual) Test with Windows machine on LAN | Integration test |
