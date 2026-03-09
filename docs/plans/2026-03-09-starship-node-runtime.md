# Starship Node Runtime — Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Starship nodes from passive heartbeat senders into functional ARCHIE nodes with agent runtime, bidirectional mesh sharing, and a manifest-style agents tab.

**Architecture:** 4-container Docker Compose stack (Ollama + sync_service + PostgreSQL + node_api Flask). All communication is outbound HTTPS polling — no inbound ports. Sync service gains `agent_config` and `job_request` handlers. Heartbeat advertises idle agents. Starship Agents tab gets Bridge Command manifest-style cards.

**Tech Stack:** Python 3.11, Flask, PostgreSQL, Docker Compose, Ollama, standard library HTTP (no pip deps on node)

**Design Doc:** `docs/plans/2026-03-09-starship-node-runtime-design.md`

---

## Task 1: Node Database Schema + Docker Compose Expansion

**Files:**
- Modify: `node_client/docker-compose.node.yml`
- Create: `node_client/migrations/001_node_schema.sql`
- Create: `node_client/Dockerfile.node`

**Step 1: Create the node Dockerfile**

This builds a slim image with node_sync.py + node_api.py so we don't mount raw .py files.

Create `node_client/Dockerfile.node`:

```dockerfile
FROM python:3.11-slim

RUN pip install --no-cache-dir flask psycopg2-binary requests

WORKDIR /app
COPY node_sync.py node_api.py ./
COPY migrations/ ./migrations/

CMD ["python3", "-u", "node_sync.py"]
```

**Step 2: Create the node database migration**

Create `node_client/migrations/001_node_schema.sql`:

```sql
-- Node-local schema for agent configs and job tracking
CREATE TABLE IF NOT EXISTS node_agent_configs (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    model VARCHAR(200) NOT NULL,
    system_prompt TEXT,
    station_codes TEXT[] DEFAULT '{}',
    capabilities TEXT[] DEFAULT '{}',
    sync_id BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS node_jobs (
    id SERIAL PRIMARY KEY,
    hub_job_id BIGINT,
    sync_id BIGINT,
    agent_name VARCHAR(100) NOT NULL,
    job_type VARCHAR(50),
    description TEXT,
    prompt TEXT,
    timeout_seconds INT DEFAULT 300,
    status VARCHAR(20) DEFAULT 'pending',
    output TEXT,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_node_jobs_status ON node_jobs(status);
CREATE INDEX IF NOT EXISTS idx_node_jobs_agent ON node_jobs(agent_name);
```

**Step 3: Expand docker-compose.node.yml to 4 services**

Modify `node_client/docker-compose.node.yml` — replace the full file:

```yaml
###############################################################################
# A.R.C.H.I.E. Starship Node - Docker Compose (Phase 1)
# ============================================================================
# 4-service stack: Ollama + Postgres + sync_service + node_api
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
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - starship_net

  postgres:
    image: postgres:16-alpine
    container_name: archie_starship_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: archie_node
      POSTGRES_PASSWORD: ${DB_PASSWORD:-archie_node_default}
      POSTGRES_DB: archie_node
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U archie_node"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - starship_net

  sync:
    build:
      context: .
      dockerfile: Dockerfile.node
    container_name: archie_starship_sync
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      NODE_ID: ${NODE_ID}
      HUB_URL: ${HUB_URL}
      HUB_API_KEY: ${HUB_API_KEY}
      OLLAMA_HOST: http://ollama:11434
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      HEARTBEAT_INTERVAL: "30"
      SYNC_POLL_INTERVAL: "60"
      DEPLOYMENT_MODE: "starship"
    command: ["python3", "-u", "node_sync.py"]
    networks:
      - starship_net

  node_api:
    build:
      context: .
      dockerfile: Dockerfile.node
    container_name: archie_starship_api
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://archie_node:${DB_PASSWORD:-archie_node_default}@postgres:5432/archie_node
      OLLAMA_HOST: http://ollama:11434
      NODE_ID: ${NODE_ID}
    command: ["python3", "-u", "node_api.py"]
    ports:
      - "${NODE_API_PORT:-3001}:3001"
    networks:
      - starship_net

volumes:
  ollama_data:
  pg_data:

networks:
  starship_net:
    driver: bridge
```

**Step 4: Commit**

```bash
git add node_client/Dockerfile.node node_client/migrations/001_node_schema.sql node_client/docker-compose.node.yml
git commit -m "feat(starship): expand node to 4-container stack with Postgres + node_api"
```

---

## Task 2: Node API (Flask app for local agent runtime)

**Files:**
- Create: `node_client/node_api.py`

**Step 1: Create the Node API Flask app**

Create `node_client/node_api.py`:

```python
#!/usr/bin/env python3
"""
A.R.C.H.I.E. Starship Node API
================================
Lightweight Flask app for local agent runtime.
Receives agent configs via sync, serves local status, queues jobs.
"""

import json
import logging
import os
import sys

from flask import Flask, jsonify, request
import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("archie_node_api")

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://archie_node:archie_node_default@postgres:5432/archie_node")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
NODE_ID = os.environ.get("NODE_ID", "unknown")


def get_db():
    """Get a database connection."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


@app.route("/health")
def health():
    """Health check endpoint."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "node_id": NODE_ID,
        "database": "connected" if db_ok else "disconnected",
    })


@app.route("/api/agents")
def list_agents():
    """List all agent configs stored locally."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM node_agent_configs ORDER BY agent_name")
    agents = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"agents": [dict(a) for a in agents]})


@app.route("/api/jobs")
def list_jobs():
    """List recent jobs."""
    limit = request.args.get("limit", 20, type=int)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM node_jobs ORDER BY created_at DESC LIMIT %s",
        (limit,)
    )
    jobs = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"jobs": [dict(j) for j in jobs]})


@app.route("/api/status")
def node_status():
    """Node status with agent count and job stats."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as count FROM node_agent_configs")
    agent_count = cur.fetchone()["count"]
    cur.execute(
        "SELECT status, COUNT(*) as count FROM node_jobs GROUP BY status"
    )
    job_stats = {r["status"]: r["count"] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return jsonify({
        "node_id": NODE_ID,
        "agents": agent_count,
        "jobs": job_stats,
    })


if __name__ == "__main__":
    logger.info("Starting Node API on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)
```

**Step 2: Commit**

```bash
git add node_client/node_api.py
git commit -m "feat(starship): add node_api.py Flask app for local agent runtime"
```

---

## Task 3: Agent Config Sync Handler (node_sync.py)

**Files:**
- Modify: `node_client/node_sync.py` (lines 446-487)

**Step 1: Add database helper to node_sync.py**

Add after line 35 (after the urllib import block), before the logging section:

```python
# ---------------------------------------------------------------------------
# Optional psycopg2 import — needed for local DB operations
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    psycopg2 = None
    _HAS_PSYCOPG2 = False
```

Add a DB helper function after `load_config()` (after line ~100):

```python
def _get_node_db():
    """Get a connection to the local node database (if available)."""
    if not _HAS_PSYCOPG2:
        logger.warning("psycopg2 not installed — local DB operations disabled")
        return None
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.error("Failed to connect to local DB: %s", e)
        return None
```

**Step 2: Add agent_config handler**

Replace the `handle_sync` function and add new handlers at line 446:

```python
def handle_sync(config, sync_type, payload):
    """
    Dispatch a sync command to the appropriate handler.
    """
    handlers = {
        "code_update": _handle_code_update,
        "iaae_policy": _handle_iaae_policy,
        "model_recommend": _handle_model_recommend,
        "agent_config": _handle_agent_config,
        "job_request": _handle_job_request,
    }

    handler = handlers.get(sync_type)
    if handler:
        return handler(config, payload)
    else:
        logger.warning("Unknown sync_type '%s' — skipping", sync_type)
        return {"status": "skipped", "error": f"Unknown sync_type: {sync_type}"}
```

Add after the existing `_handle_model_recommend` function (after line 487):

```python
def _handle_agent_config(config, payload):
    """Handle agent_config sync — save crew manifest to local Postgres."""
    agents = payload.get("agents", [])
    if not agents:
        logger.warning("[agent_config] Empty agents list — skipping")
        return {"status": "failed", "error": "Empty agents list"}

    conn = _get_node_db()
    if not conn:
        logger.error("[agent_config] No local DB — cannot save agent configs")
        return {"status": "failed", "error": "Local database unavailable"}

    try:
        cur = conn.cursor()
        saved = 0
        for agent in agents:
            cur.execute(
                """
                INSERT INTO node_agent_configs
                    (agent_name, display_name, model, system_prompt,
                     station_codes, capabilities, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (agent_name) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    model = EXCLUDED.model,
                    system_prompt = EXCLUDED.system_prompt,
                    station_codes = EXCLUDED.station_codes,
                    capabilities = EXCLUDED.capabilities,
                    updated_at = NOW()
                """,
                (
                    agent["name"],
                    agent.get("display_name", agent["name"]),
                    agent.get("model", "mistral:latest"),
                    agent.get("system_prompt", ""),
                    agent.get("station_codes", []),
                    agent.get("capabilities", []),
                ),
            )
            saved += 1
        conn.commit()
        cur.close()
        conn.close()
        logger.info("[agent_config] Saved %d agent configs to local DB", saved)
        return {"status": "acknowledged", "agents_saved": saved}
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error("[agent_config] Failed to save: %s", e)
        return {"status": "failed", "error": str(e)}


def _handle_job_request(config, payload):
    """Handle job_request sync — save job to local DB and execute via Ollama."""
    job_id = payload.get("job_id")
    agent_name = payload.get("agent_name")
    prompt = payload.get("prompt", "")
    timeout = payload.get("timeout_seconds", 300)

    if not agent_name or not prompt:
        return {"status": "failed", "error": "Missing agent_name or prompt"}

    conn = _get_node_db()
    if not conn:
        return {"status": "failed", "error": "Local database unavailable"}

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Save job to local DB
        cur.execute(
            """
            INSERT INTO node_jobs
                (hub_job_id, agent_name, job_type, description, prompt,
                 timeout_seconds, status, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'running', NOW())
            RETURNING id
            """,
            (
                job_id,
                agent_name,
                payload.get("job_type", "inference"),
                payload.get("description", ""),
                prompt,
                timeout,
            ),
        )
        local_job_id = cur.fetchone()["id"]
        conn.commit()

        # Look up agent config for model + system_prompt
        cur.execute(
            "SELECT model, system_prompt FROM node_agent_configs WHERE agent_name = %s",
            (agent_name,)
        )
        agent_cfg = cur.fetchone()
        if not agent_cfg:
            cur.execute(
                "UPDATE node_jobs SET status = 'failed', error_message = 'Agent not configured', completed_at = NOW() WHERE id = %s",
                (local_job_id,)
            )
            conn.commit()
            cur.close()
            conn.close()
            return {"status": "failed", "error": f"Agent '{agent_name}' not configured on this node"}

        model = agent_cfg["model"]
        system_prompt = agent_cfg["system_prompt"] or ""

        # Call Ollama
        ollama_host = config.get("ollama_host", "http://ollama:11434")
        ollama_payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            ollama_payload["system"] = system_prompt

        logger.info("[job_request] Executing job %s on agent '%s' (model: %s)", job_id, agent_name, model)

        try:
            import time
            start = time.time()
            status_code, resp = _http_request(
                "POST",
                f"{ollama_host}/api/generate",
                json_body=ollama_payload,
                timeout=timeout,
            )
            elapsed = time.time() - start

            if status_code == 200 and isinstance(resp, dict):
                output = resp.get("response", "")
                cur.execute(
                    "UPDATE node_jobs SET status = 'completed', output = %s, completed_at = NOW() WHERE id = %s",
                    (output, local_job_id),
                )
                conn.commit()
                logger.info("[job_request] Job %s completed in %.1fs (%d chars)", job_id, elapsed, len(output))
                result = {"status": "completed", "output": output, "elapsed_seconds": round(elapsed, 1)}
            else:
                error = f"Ollama returned HTTP {status_code}"
                cur.execute(
                    "UPDATE node_jobs SET status = 'failed', error_message = %s, completed_at = NOW() WHERE id = %s",
                    (error, local_job_id),
                )
                conn.commit()
                result = {"status": "failed", "error": error}

        except Exception as ollama_err:
            error = f"Ollama call failed: {ollama_err}"
            cur.execute(
                "UPDATE node_jobs SET status = 'failed', error_message = %s, completed_at = NOW() WHERE id = %s",
                (error, local_job_id),
            )
            conn.commit()
            result = {"status": "failed", "error": error}

        cur.close()
        conn.close()
        return result

    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error("[job_request] Failed: %s", e)
        return {"status": "failed", "error": str(e)}
```

**Step 3: Update poll_syncs to pass results back in ACK**

Find the `poll_syncs` function and update the ACK call to include handler results. The current ACK sends just status='acknowledged'. Update it to include the handler's result payload.

In `poll_syncs()`, find where `handle_sync()` is called and `_ack_sync()` follows. Change the ACK to include the handler result:

```python
# In poll_syncs(), after handle_sync() call:
result = handle_sync(config, sync_type, payload)
ack_status = result.get("status", "acknowledged") if result else "acknowledged"
ack_payload = result if result else {}
# Pass ack_status and ack_payload to _ack_sync
```

**Step 4: Commit**

```bash
git add node_client/node_sync.py
git commit -m "feat(starship): add agent_config + job_request sync handlers with local DB"
```

---

## Task 4: Heartbeat Advertise Idle Agents

**Files:**
- Modify: `node_client/node_sync.py` — `send_heartbeat()` function (line 328)
- Modify: `platform_v2/tools/bridge/routes.py` — `node_heartbeat()` handler (line 4214)

**Step 1: Add idle agent info to heartbeat payload**

In `node_client/node_sync.py`, find `send_heartbeat()` (line 328). After the existing payload dict (around line 348), add:

```python
    # Advertise idle agents (for mesh sharing)
    idle_agents = _get_idle_agents(config)
    if idle_agents:
        payload["idle_agents"] = idle_agents
```

Add helper function before `send_heartbeat()`:

```python
def _get_idle_agents(config):
    """Query local DB for agents not currently running a job."""
    conn = _get_node_db()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT nac.agent_name, nac.model, nac.station_codes, nac.capabilities
            FROM node_agent_configs nac
            WHERE NOT EXISTS (
                SELECT 1 FROM node_jobs nj
                WHERE nj.agent_name = nac.agent_name AND nj.status = 'running'
            )
            """
        )
        agents = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return agents
    except Exception as e:
        logger.warning("Failed to query idle agents: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return []
```

**Step 2: Update hub heartbeat handler to store idle_agents**

In `platform_v2/tools/bridge/routes.py`, find `node_heartbeat()` (line 4214). After the existing `UPDATE remote_nodes` query, add storage of `idle_agents` in the node's metadata:

```python
        # Store idle agents in node metadata (for mesh dispatcher)
        idle_agents = data.get("idle_agents")
        if idle_agents is not None:
            cur.execute(
                """
                UPDATE remote_nodes
                SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('idle_agents', %s::jsonb)
                WHERE node_id = %s
                """,
                (json.dumps(idle_agents), node_id),
            )
```

**Step 3: Commit**

```bash
git add node_client/node_sync.py platform_v2/tools/bridge/routes.py
git commit -m "feat(starship): heartbeat advertises idle agents for mesh sharing"
```

---

## Task 5: Hub Push Config — Wire Up Full Pipeline

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` — `api_push_agent_config()` (line 1312)

**Step 1: Enhance the push-config payload**

The existing `api_push_agent_config()` at line 1312 already writes to `mesh_sync_log` with `sync_type='agent_config'`. Verify it includes the full agent data (name, display_name, model, system_prompt, station_codes, capabilities).

Read lines 1312-1380 and ensure the payload includes all fields the node handler expects. The payload should match the `agent_config` format from the design doc.

If the payload only includes partial data, update it to include:
```python
payload = {
    "agents": [
        {
            "name": agent["name"],
            "display_name": agent["display_name"],
            "model": agent["model"],
            "system_prompt": agent.get("system_prompt", ""),
            "station_codes": agent.get("station_codes", []),
            "capabilities": agent.get("capabilities", []),
        }
        for agent in node_agents
    ]
}
```

**Step 2: Commit**

```bash
git add platform_v2/tools/starship/routes.py
git commit -m "fix(starship): ensure push-config payload includes all agent fields"
```

---

## Task 6: Starship Agents Tab — Bridge Manifest-Style Cards

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` (lines 470-494, 851-947)
- Modify: `platform_v2/tools/starship/routes.py` — add manifest endpoint

**Step 1: Add node crew manifest endpoint**

In `platform_v2/tools/starship/routes.py`, add a new endpoint that returns agent data in the same format as Bridge's `get_crew_manifest()`:

```python
@starship_bp.route("/api/nodes/<int:node_id>/crew-manifest")
@login_required
def api_node_crew_manifest(node_id):
    """Return node agents in Bridge manifest-compatible format for rich card rendering."""
    with get_db_cursor() as (conn, cur):
        # Get all node agents
        cur.execute(
            """
            SELECT na.id as agent_id, na.name, na.display_name as full_name,
                   na.title, na.model, na.status,
                   na.station_codes, na.allowed
            FROM node_agents na
            WHERE na.node_id = %s
            ORDER BY na.name
            """,
            (node_id,),
        )
        agents = cur.fetchall()

        # Get node's Ollama models for LLM readiness check
        cur.execute(
            "SELECT node_id FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node_row = cur.fetchone()
        node_str_id = node_row["node_id"] if node_row else ""

        cur.execute(
            """
            SELECT model_name, is_available
            FROM node_models
            WHERE node_id = %s
            """,
            (node_id,),
        )
        models = cur.fetchall()
        available_models = {
            m["model_name"].split(":")[0].lower()
            for m in models if m["is_available"]
        }
        available_exact = {m["model_name"] for m in models if m["is_available"]}

        # Get station colors
        cur.execute("SELECT station_code, color FROM bridge_stations")
        station_colors = {s["station_code"]: s["color"] for s in cur.fetchall()}

        manifest = []
        for a in agents:
            agent_model = a["model"] or ""
            agent_base = agent_model.split(":")[0].lower()

            # Determine LLM readiness: model_ready / model_offline
            if agent_model in available_exact or agent_base in available_models:
                llm_status = "loaded"  # On node = available
            else:
                llm_status = "barracked"  # Not available on node

            # Station colors for this agent
            codes = a["station_codes"] or []
            colors = [station_colors.get(c, "#00e5ff") for c in codes]

            manifest.append({
                "agent_id": a["agent_id"],
                "name": a["name"],
                "full_name": a["full_name"] or a["name"],
                "title": a["title"] or "",
                "model": agent_model,
                "status": "active" if a["status"] == "active" else "idle",
                "llm_status": llm_status,
                "station": codes[0] if codes else "UNASSIGNED",
                "station_codes": codes,
                "station_colors": colors,
                "allowed": a["allowed"] if a["allowed"] is not None else True,
                "wellness": {"stress": 0, "energy": 1.0, "mood": "ready"},
                "stats_24h": {"dispatches": 0, "success_rate": 0},
                "current_job": None,
            })

        return jsonify({"success": True, "crew": manifest})
```

**Step 2: Replace agents tab HTML**

In `starship.html`, replace the `#panel-agents` content (lines 470-494) with a manifest-style layout:

```html
<!-- AGENTS TAB -->
<div class="sc-panel" id="panel-agents">
    <div class="sc-section">
        <h4>CREW MANIFEST</h4>
        <div class="sc-agent-summary" id="d-agent-summary"></div>
        <div id="d-agents-manifest" class="crew-manifest-grid">
            <span class="sc-label">Loading...</span>
        </div>
        <div id="agent-recommendations" style="display:none; margin-top: 20px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #a78bfa; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; letter-spacing: 1px;">RECOMMENDED CREW</span>
                <button class="sc-btn-small" style="background: rgba(167,139,250,0.15); color: #a78bfa; border: 1px solid rgba(167,139,250,0.3); font-size: 0.65rem; padding: 3px 8px;" onclick="addAllRecommended()">ADD ALL</button>
            </div>
            <div id="recommendation-cards" style="display: flex; flex-wrap: wrap; gap: 8px;"></div>
            <div id="station-suggestions" style="margin-top: 8px;"></div>
        </div>
        <div id="agent-sync-status" style="display: flex; align-items: center; justify-content: space-between; margin-top: 16px; padding: 10px 16px; background: rgba(0,0,0,0.3); border: 1px solid rgba(0,229,255,0.1); border-radius: 6px;">
            <span id="sync-indicator" style="color: rgba(255,255,255,0.4); font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem;">Agent config not synced</span>
            <button class="sc-btn-small" onclick="pushAgentConfig()">PUSH CHANGES TO NODE</button>
        </div>
    </div>
</div>
```

**Step 3: Replace renderNodeAgents() JavaScript**

Replace the JavaScript function `renderNodeAgents()` (lines 851-947 area) with a manifest-style renderer that uses `crew-agent-card` CSS from Bridge:

```javascript
// Fetch manifest data and render cards
async function renderNodeManifest(nodeDbId) {
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/crew-manifest');
        var data = await resp.json();
        if (!data.success) return;

        var crew = data.crew || [];
        var grid = document.getElementById('d-agents-manifest');
        grid.textContent = '';

        // Summary
        var agSummary = document.getElementById('d-agent-summary');
        agSummary.textContent = '';
        var allowed = crew.filter(function(a) { return a.allowed; }).length;
        var modelReady = crew.filter(function(a) { return a.llm_status === 'loaded'; }).length;
        buildSummarySpan(agSummary, allowed, 'active');
        buildSummarySpan(agSummary, modelReady, 'models ready');
        buildSummarySpan(agSummary, crew.length, 'total crew');

        crew.forEach(function(agent) {
            grid.appendChild(_renderStarshipAgentCard(agent));
        });

        if (crew.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'sc-label';
            empty.textContent = 'No agents assigned to this node.';
            grid.appendChild(empty);
        }
    } catch (e) {
        console.error('Manifest load failed:', e);
    }
}

function _renderStarshipAgentCard(agent) {
    var card = document.createElement('div');
    card.className = 'crew-agent-card';
    card.setAttribute('data-station', agent.station);

    // Station-colored left border
    var colors = agent.station_colors || [];
    if (colors.length > 0) {
        card.style.borderLeftColor = colors[0];
    }

    // Top row: name + badges
    var top = document.createElement('div');
    top.className = 'crew-agent-top';

    var name = document.createElement('span');
    name.className = 'crew-agent-name';
    name.textContent = agent.full_name || agent.name;

    var badges = document.createElement('div');
    badges.className = 'crew-agent-badges';

    // Status badge
    var statusBadge = document.createElement('span');
    statusBadge.className = 'crew-status-badge ' + agent.status;
    statusBadge.textContent = agent.status;
    badges.appendChild(statusBadge);

    // LLM readiness badge (MODEL READY / MODEL OFFLINE)
    var llmBadge = document.createElement('span');
    if (agent.llm_status === 'loaded') {
        llmBadge.className = 'crew-llm-badge loaded';
        llmBadge.textContent = 'MODEL READY';
        llmBadge.title = 'Model available on this node';
    } else {
        llmBadge.className = 'crew-llm-badge barracked';
        llmBadge.textContent = 'MODEL OFFLINE';
        llmBadge.title = 'Model not available on this node';
    }
    badges.appendChild(llmBadge);

    // Sharing badge
    var shareBadge = document.createElement('span');
    shareBadge.className = 'crew-status-badge ' + (agent.allowed ? 'active' : 'idle');
    shareBadge.textContent = agent.allowed ? 'ENABLED' : 'DISABLED';
    badges.appendChild(shareBadge);

    top.appendChild(name);
    top.appendChild(badges);
    card.appendChild(top);

    // Callsign subtitle
    if (agent.full_name && agent.full_name !== agent.name) {
        var subtitle = document.createElement('div');
        subtitle.style.cssText = 'font-size: 0.6rem; color: rgba(255,255,255,0.35); margin-top: -2px;';
        subtitle.textContent = agent.name + (agent.title ? ' — ' + agent.title : '');
        card.appendChild(subtitle);
    }

    // Meta row: station + model
    var meta = document.createElement('div');
    meta.className = 'crew-agent-meta';

    var stationSpan = document.createElement('span');
    stationSpan.textContent = agent.station;
    if (colors.length > 0) stationSpan.style.color = colors[0];
    meta.appendChild(stationSpan);

    var modelSpan = document.createElement('span');
    modelSpan.textContent = (agent.model || '').replace(':latest', '');
    meta.appendChild(modelSpan);

    // Station tags
    var tags = document.createElement('div');
    tags.style.cssText = 'display: flex; gap: 4px; flex-wrap: wrap;';
    (agent.station_codes || []).forEach(function(sc, i) {
        var tag = document.createElement('span');
        tag.className = 'sc-agent-station-tag';
        tag.textContent = sc;
        var c = (agent.station_colors || [])[i];
        if (c) { tag.style.borderColor = c + '44'; tag.style.color = c; }
        tags.appendChild(tag);
    });

    meta.appendChild(tags);
    card.appendChild(meta);

    // Active job (if any)
    if (agent.current_job) {
        var jobRow = document.createElement('div');
        jobRow.className = 'crew-agent-job';
        var jobDesc = document.createElement('span');
        jobDesc.textContent = agent.current_job.description || 'Working...';
        jobDesc.style.cssText = 'max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
        var jobBar = document.createElement('div');
        jobBar.className = 'crew-job-bar';
        var jobFill = document.createElement('div');
        jobFill.className = 'crew-job-bar-fill';
        jobFill.style.width = Math.min(agent.current_job.progress_pct || 0, 100) + '%';
        jobBar.appendChild(jobFill);
        jobRow.appendChild(jobDesc);
        jobRow.appendChild(jobBar);
        card.appendChild(jobRow);
    }

    // Remove button (bottom-right)
    var actions = document.createElement('div');
    actions.style.cssText = 'display: flex; justify-content: flex-end; margin-top: 6px; gap: 6px;';

    var removeBtn = document.createElement('button');
    removeBtn.className = 'sc-btn-small';
    removeBtn.style.cssText = 'background:rgba(255,68,68,0.15);color:#ff4444;border:1px solid rgba(255,68,68,0.3);font-size:0.6rem;padding:2px 6px;';
    removeBtn.textContent = 'REMOVE';
    removeBtn.onclick = (function(id) { return function(e) { e.stopPropagation(); removeAgentFromNode(id); }; })(agent.agent_id);
    actions.appendChild(removeBtn);

    var toggleBtn = document.createElement('button');
    toggleBtn.className = 'sc-btn-small';
    toggleBtn.style.cssText = agent.allowed
        ? 'background:rgba(0,229,255,0.15);color:#00e5ff;border:1px solid rgba(0,229,255,0.3);font-size:0.6rem;padding:2px 6px;'
        : 'background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.3);border:1px solid rgba(255,255,255,0.1);font-size:0.6rem;padding:2px 6px;';
    toggleBtn.textContent = agent.allowed ? 'DISABLE' : 'ENABLE';
    toggleBtn.onclick = (function(id, allowed) { return function(e) { e.stopPropagation(); toggleAgentAccess(id, !allowed); }; })(agent.agent_id, agent.allowed);
    actions.appendChild(toggleBtn);

    card.appendChild(actions);

    return card;
}
```

**Step 4: Wire manifest render into selectNode()**

In `selectNode()`, change the agents tab loading to call `renderNodeManifest(nodeDbId)` instead of the old inline rendering.

**Step 5: Include Bridge crew card CSS**

Add to the `<style>` section or include `bridge.html`'s crew card styles. The key classes needed:
- `.crew-manifest-grid` — CSS grid, `grid-template-columns: repeat(auto-fill, minmax(260px, 1fr))`, gap 12px
- `.crew-agent-card` — Card with dark background, border-left 3px, border-radius 8px, padding 12px
- `.crew-agent-top` — Flex row, space-between
- `.crew-agent-name` — Font 0.85rem, white
- `.crew-agent-badges` — Flex row, gap 4px, flex-wrap
- `.crew-status-badge`, `.crew-llm-badge` — Small pill badges
- `.crew-agent-meta` — Flex row, gap 8px, muted text
- `.crew-agent-job` — Job progress bar

Copy these styles from Bridge or define inline. Since Bridge CSS is global (loaded in base template), the classes may already be available. Check if `bridge.html` styles are global — if not, extract the crew card CSS into the starship template's `<style>` block.

**Step 6: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): manifest-style agent cards matching Bridge Command crew tab"
```

---

## Task 7: Hub Migration — Add metadata JSONB to remote_nodes (if missing)

**Files:**
- Create: `database/migrations/143_node_metadata_column.sql`

**Step 1: Check if remote_nodes has metadata column**

Run: `docker exec archie_database psql -U archie -d archie -c "\d remote_nodes" | grep metadata`

If missing, create migration:

```sql
-- Add metadata JSONB column to remote_nodes for idle_agents and other node-reported data
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
COMMENT ON COLUMN remote_nodes.metadata IS 'Node-reported metadata including idle_agents from heartbeat';
```

**Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /migrations/143_node_metadata_column.sql
```

**Step 3: Commit**

```bash
git add database/migrations/143_node_metadata_column.sql
git commit -m "feat(starship): add metadata JSONB column to remote_nodes"
```

---

## Task 8: One-Click Onboarding — Enhanced Install Scripts

**Files:**
- Modify: `platform_v2/tools/starship/routes.py` — enhance install endpoints
- Modify: `node_client/install.sh` — update for 4-container stack
- Modify: `node_client/install.ps1` — update for 4-container stack

**Step 1: Update install.sh for Phase 1 stack**

The existing `install.sh` downloads `docker-compose.node.yml` + `node_sync.py`. Update to also download:
- `Dockerfile.node`
- `node_api.py`
- `migrations/001_node_schema.sql`

Update the download section to pull all required files and create the migrations directory.

**Step 2: Update install.ps1 for Phase 1 stack**

Same as above but for PowerShell. Download the additional files.

**Step 3: Update the setup-instructions endpoint**

Ensure `api_setup_instructions()` returns the updated file list and correct docker compose command.

**Step 4: Commit**

```bash
git add node_client/install.sh node_client/install.ps1 platform_v2/tools/starship/routes.py
git commit -m "feat(starship): update install scripts for 4-container Phase 1 stack"
```

---

## Task 9: + ADD NODE Button Enhancement

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` — add node modal

**Step 1: Enhance the Add Node flow**

The existing `requestNewNode()` function and modal should be updated to:
1. Show a clear step-by-step: "Name your node" → "Download config" → "Run install command"
2. Display the one-liner install command (PowerShell / bash)
3. Show live status polling: "Waiting for node to connect..."
4. Auto-redirect to node detail when first heartbeat arrives

Update the modal content with tabs for Windows (PowerShell) and Linux (bash) install commands.

**Step 2: Add live connection polling**

```javascript
function pollNodeConnection(nodeId) {
    var interval = setInterval(async function() {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeId + '/status');
        var data = await resp.json();
        if (data.status === 'online') {
            clearInterval(interval);
            document.getElementById('node-connect-status').textContent = '✓ Node connected!';
            document.getElementById('node-connect-status').style.color = '#4ade80';
            setTimeout(function() { selectNode(nodeId); }, 1000);
        }
    }, 5000);
    // Stop polling after 5 minutes
    setTimeout(function() { clearInterval(interval); }, 300000);
}
```

**Step 3: Commit**

```bash
git add platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): enhanced ADD NODE onboarding with live connection polling"
```

---

## Task 10: Privacy Controls Tab

**Files:**
- Modify: `platform_v2/tools/starship/templates/tools/starship/starship.html` — privacy tab content

**Step 1: Add mesh sharing controls**

In the existing Privacy tab panel, add toggles:
- "Share idle agents with fleet" — on/off toggle (updates `privacy_settings.share_agents`)
- "Max concurrent shared jobs" — number input (1-5, default 2)
- "Priority: local first" — always on, display as info

These should POST to an existing or new endpoint that updates `remote_nodes.privacy_settings` JSONB.

**Step 2: Add privacy settings endpoint**

In `routes.py`, add:

```python
@starship_bp.route("/api/nodes/<int:node_id>/privacy", methods=["GET", "POST"])
@login_required
def api_node_privacy(node_id):
    """Get or update node privacy settings."""
    # ...
```

**Step 3: Commit**

```bash
git add platform_v2/tools/starship/routes.py platform_v2/tools/starship/templates/tools/starship/starship.html
git commit -m "feat(starship): privacy controls for mesh agent sharing"
```

---

## Task 11: Integration Test — KYTRAN-StarShip

**Step 1: Rebuild node Docker stack on KYTRAN-StarShip**

```bash
cd ~/archie-node
docker compose down
docker compose build
docker compose up -d
```

**Step 2: Verify all 4 containers running**

```bash
docker compose ps
# Expected: ollama (healthy), postgres (healthy), sync (running), node_api (running)
```

**Step 3: Push agent config from hub**

1. Go to Starship Command → select KYTRAN-StarShip
2. Go to Agents tab → click "PUSH CHANGES TO NODE"
3. Verify sync-indicator shows "Config synced"

**Step 4: Verify agent configs landed on node**

```bash
docker exec archie_starship_db psql -U archie_node -d archie_node -c "SELECT agent_name, model FROM node_agent_configs"
# Expected: 9 agent rows
```

**Step 5: Verify manifest cards render**

1. Refresh Starship Command → Agents tab
2. Should show crew-manifest-grid with rich cards (status badges, MODEL READY/OFFLINE, station tags)

**Step 6: Check heartbeat includes idle_agents**

Check platform logs for idle_agents in heartbeat data:
```bash
docker logs archie_platform 2>&1 | grep idle_agents | tail -5
```

**Step 7: Commit any fixes**

```bash
git add -A
git commit -m "fix(starship): integration test fixes for Phase 1 node runtime"
```

---

## Task 12: Deploy + Dev HQ Update

**Step 1: Deploy to production**

```bash
docker compose restart archie_platform
```

**Step 2: Update Dev HQ**

```
mcp complete_task (Task 816: Node Docker stack)
mcp complete_task (Task 817: Agent config sync handler)
mcp complete_task (Task 818: Heartbeat advertise idle agents)
mcp complete_task (Task 819: One-click node onboarding)
mcp complete_task (Task 820: Starship Agents tab manifest cards)
mcp update_project_understanding (Project 121)
mcp log_decision "Phase 1 node runtime: 4-container Docker Compose, agent_config + job_request sync handlers, manifest-style agents tab"
```

**Step 3: Final commit + push**

```bash
git push origin main
```
