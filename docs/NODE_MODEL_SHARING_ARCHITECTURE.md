# Node Model Sharing Architecture

**Version**: 1.0
**Date**: 2026-01-22
**Status**: IMPLEMENTED (Phases 74-76 COMPLETE)

---

## 1. Overview

This document describes how remote nodes share their AI models (Ollama, image generation, etc.) with the central A.R.C.H.I.E. Bridge for intelligent task routing.

### Key Principles

1. **Bridge is Central** - The Bridge manages all stations, workers, and task routing
2. **Nodes Provide Compute** - Nodes expose their available models to the Bridge
3. **Dynamic Discovery** - Bridge dynamically reads node capabilities instead of hardcoded endpoints
4. **Admin Control** - Simple button to enable/disable node model sharing

---

## 2. Current Architecture (Before)

```
┌─────────────────────────────────────────────────────────────────┐
│                        A.R.C.H.I.E. BRIDGE                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ai_bridge/archie_bridge.py                              │   │
│  │                                                          │   │
│  │  OLLAMA_HOST = 'http://192.168.1.246:11434' (HARDCODED) │   │
│  │                                                          │   │
│  │  call_ollama() → Always goes to .246                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│                    ┌──────────────────┐                        │
│                    │  192.168.1.246   │                        │
│                    │  (Single Ollama) │                        │
│                    └──────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

**Problems:**
- Single point of failure
- No load balancing
- Can't use other machines' GPUs
- Hardcoded endpoint

---

## 3. New Architecture (After)

```
┌─────────────────────────────────────────────────────────────────┐
│                        A.R.C.H.I.E. BRIDGE                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ai_bridge/archie_bridge.py                              │   │
│  │                                                          │   │
│  │  get_ollama_nodes() → Reads from remote_nodes table     │   │
│  │  select_best_node() → Load balancing + capability match │   │
│  │  call_ollama(node) → Routes to selected node            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│     │ .246 (KYTRAN)│ │ .109 (Main)  │ │ .247 (GPU)   │         │
│     │ - Ollama     │ │ - Ollama     │ │ - Ollama     │         │
│     │ - RTX 3070   │ │ - RTX 4090   │ │ - A100       │         │
│     │ - Foocus     │ │ - ComfyUI    │ │ - A1111      │         │
│     └──────────────┘ └──────────────┘ └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘

                    remote_nodes table
┌──────────────────────────────────────────────────────────────────┐
│ node_id | vpn_ip    | ollama_available | bridge_enabled | models │
│─────────┼───────────┼──────────────────┼────────────────┼────────│
│ node_1  | .246      | true             | true           | [...]  │
│ node_2  | .109      | true             | true           | [...]  │
│ node_3  | .247      | true             | false          | [...]  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema Changes

### 4.1 Add to `remote_nodes` table

```sql
-- Add bridge sharing control
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS bridge_enabled BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS bridge_priority INTEGER DEFAULT 50;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS bridge_weight INTEGER DEFAULT 100;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS ollama_models JSONB DEFAULT '[]';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS last_model_sync TIMESTAMP;
```

### 4.2 New table: `node_ollama_models`

```sql
CREATE TABLE IF NOT EXISTS node_ollama_models (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    model_name VARCHAR(100) NOT NULL,
    model_size_gb DECIMAL(6,2),
    quantization VARCHAR(20),
    context_length INTEGER,
    capabilities TEXT[], -- ['chat', 'code', 'vision', 'embedding']
    is_available BOOLEAN DEFAULT true,
    last_used TIMESTAMP,
    avg_response_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(node_id, model_name)
);

CREATE INDEX idx_node_ollama_models_node ON node_ollama_models(node_id);
CREATE INDEX idx_node_ollama_models_available ON node_ollama_models(is_available);
```

---

## 5. Node Model Sync Process

### 5.1 Node Reports Models on Heartbeat

Each node periodically reports its available Ollama models:

```python
# node_client/heartbeat.py
def get_ollama_models():
    """Fetch available models from local Ollama"""
    try:
        response = requests.get('http://localhost:11434/api/tags')
        if response.status_code == 200:
            return response.json().get('models', [])
    except:
        return []

def send_heartbeat():
    payload = {
        'node_id': NODE_ID,
        'status': 'online',
        'current_load': get_cpu_load(),
        'ollama_models': get_ollama_models(),
        'gpu_memory_free': get_gpu_memory()
    }
    requests.post(f'{CENTRAL_URL}/api/nodes/heartbeat', json=payload)
```

### 5.2 Central Server Updates Model Registry

```python
# platform_v2/tools/bridge/routes.py
@bridge_bp.route('/api/nodes/heartbeat', methods=['POST'])
def node_heartbeat():
    data = request.json
    node_id = data['node_id']

    # Update node status
    update_node_status(node_id, data['status'], data['current_load'])

    # Sync Ollama models
    if 'ollama_models' in data:
        sync_node_models(node_id, data['ollama_models'])

    return jsonify({'success': True})
```

---

## 6. Bridge Model Routing

### 6.1 Get Available Nodes for Model

```python
# ai_bridge/node_router.py
def get_nodes_with_model(model_name):
    """Find all bridge-enabled nodes that have a specific model"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT n.node_id, n.vpn_ip, n.port, n.current_load,
               n.bridge_priority, n.bridge_weight, n.gpu_model
        FROM remote_nodes n
        JOIN node_ollama_models m ON n.node_id = m.node_id
        WHERE n.bridge_enabled = true
          AND n.status = 'online'
          AND n.ollama_available = true
          AND m.model_name = %s
          AND m.is_available = true
        ORDER BY n.current_load ASC, n.bridge_priority DESC
    """, (model_name,))

    return cur.fetchall()

def select_best_node(model_name):
    """Select the best node for a model request (weighted random with load)"""
    nodes = get_nodes_with_model(model_name)

    if not nodes:
        return None

    # Weight by inverse load and priority
    weights = []
    for node in nodes:
        load_factor = max(0.1, 1 - (node['current_load'] / 100))
        weight = node['bridge_weight'] * load_factor * (node['bridge_priority'] / 100)
        weights.append(weight)

    # Weighted random selection
    return random.choices(nodes, weights=weights, k=1)[0]
```

### 6.2 Updated call_ollama()

```python
# ai_bridge/archie_bridge.py
def call_ollama(prompt, model='deepseek-coder-v2:16b', system_prompt=None, context=None):
    """Call Ollama API with dynamic node routing"""

    # Try to find a node with this model
    node = select_best_node(model)

    if node:
        ollama_host = f"http://{node['vpn_ip']}:{node.get('port', 11434)}"
        log_model_request(node['node_id'], model)
    else:
        # Fallback to default (for backward compatibility)
        ollama_host = os.getenv('OLLAMA_HOST', 'http://192.168.1.246:11434')

    # ... rest of the function unchanged
```

---

## 7. Admin UI - Enable Node for Bridge

### 7.1 Bridge UI Button

In the Node Network section, each node card gets a toggle:

```html
<!-- In bridge.html node card -->
<div class="node-bridge-toggle">
    <label class="toggle-switch">
        <input type="checkbox"
               id="bridge-toggle-${node.node_id}"
               ${node.bridge_enabled ? 'checked' : ''}
               onchange="toggleBridgeSharing('${node.node_id}', this.checked)">
        <span class="toggle-slider"></span>
    </label>
    <span>Share with Bridge</span>
</div>
```

### 7.2 API Endpoint

```python
@bridge_bp.route('/api/nodes/<node_id>/bridge-sharing', methods=['PUT'])
@login_required
def toggle_bridge_sharing(node_id):
    """Enable or disable a node's model sharing with Bridge"""
    data = request.json
    enabled = data.get('enabled', False)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE remote_nodes
        SET bridge_enabled = %s, updated_at = NOW()
        WHERE node_id = %s
    """, (enabled, node_id))
    conn.commit()

    # Log governance event
    log_governance_event(
        event_type='node_bridge_sharing',
        event_category='autonomy',
        action='enable' if enabled else 'disable',
        agent_id=None,
        details={'node_id': node_id}
    )

    return jsonify({'success': True, 'bridge_enabled': enabled})
```

---

## 8. Model Availability View

### 8.1 Bridge Dashboard Shows All Available Models

```sql
CREATE OR REPLACE VIEW v_bridge_available_models AS
SELECT
    m.model_name,
    COUNT(DISTINCT n.node_id) as node_count,
    ARRAY_AGG(DISTINCT n.node_name) as available_on,
    MIN(n.current_load) as min_load,
    AVG(m.avg_response_ms) as avg_response_ms
FROM node_ollama_models m
JOIN remote_nodes n ON m.node_id = n.node_id
WHERE n.bridge_enabled = true
  AND n.status = 'online'
  AND m.is_available = true
GROUP BY m.model_name
ORDER BY node_count DESC, m.model_name;
```

---

## 9. A.R.C.H.I.E. Migration to .109

### 9.1 Migration Overview

| Current | Target |
|---------|--------|
| A.R.C.H.I.E. on .248 (Docker) | A.R.C.H.I.E. on .109 (Docker) |
| Database on .248 | Database on .109 |
| Ollama on .246 | Ollama on .109 + .246 (distributed) |

### 9.2 Pre-Migration Checklist

- [ ] .109 node installed and registered
- [ ] .109 node approved and online
- [ ] .109 node has Docker installed
- [ ] .109 Ollama installed with required models
- [ ] .109 bridge_enabled = true
- [ ] Backup created on .248

### 9.3 Migration Steps

#### Phase 1: Prepare .109

```bash
# On .109
cd /mnt/archie_brain
git clone <repo> .
docker-compose build

# Don't start yet - we'll migrate data first
```

#### Phase 2: Database Migration

```bash
# On .248 - Create backup
docker exec archie_database pg_dump -U archie -d archie > /backups/pre_migration.sql

# Copy to .109
scp /backups/pre_migration.sql user@192.168.1.200:/mnt/archie_brain/backups/

# On .109 - Start only database
docker-compose up -d archie_database

# Restore
docker exec -i archie_database psql -U archie -d archie < /backups/pre_migration.sql
```

#### Phase 3: File Migration

```bash
# Rsync key directories
rsync -avz /mnt/archie_brain/conversation_logs/ user@.109:/mnt/archie_brain/conversation_logs/
rsync -avz /mnt/archie_brain/persistence/ user@.109:/mnt/archie_brain/persistence/
```

#### Phase 4: DNS/IP Cutover

```bash
# Update .env on .109
ARCHIE_HOST=192.168.1.200

# Start full stack on .109
docker-compose up -d

# Verify all services running
docker ps

# Test endpoints
curl http://192.168.1.200:3000/health
```

#### Phase 5: Update Node References

```sql
-- Update any hardcoded references to .248
UPDATE remote_nodes SET vpn_ip = '192.168.1.200' WHERE node_name = 'ARCHIE_MAIN';
```

#### Phase 6: Verify & Cleanup

- [ ] Test all Bridge functions
- [ ] Verify knowledge base accessible
- [ ] Test Ollama routing to nodes
- [ ] Keep .248 as backup for 7 days
- [ ] Decommission .248 A.R.C.H.I.E. instance

---

## 10. Implementation Phases

### Phase 70: Node Model Discovery
- Add `bridge_enabled` column to remote_nodes
- Create `node_ollama_models` table
- Update node heartbeat to report models
- Create model sync endpoint

### Phase 71: Bridge Dynamic Routing
- Create `node_router.py` with selection logic
- Update `archie_bridge.py` to use node router
- Add fallback for backward compatibility
- Add request logging per node

### Phase 72: Admin UI
- Add "Share with Bridge" toggle to node cards
- Add model availability dashboard
- Show which models are available on which nodes
- Add load indicators per node

### Phase 73: A.R.C.H.I.E. Migration
- Prepare .109 server
- Execute database migration
- Cutover and verify
- Cleanup

---

## 11. API Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/nodes/<id>/bridge-sharing` | PUT | Enable/disable node sharing |
| `/api/nodes/<id>/models` | GET | Get models on a node |
| `/api/nodes/<id>/models/sync` | POST | Force model sync |
| `/api/bridge/models` | GET | Get all available models across nodes |
| `/api/bridge/models/<model>/nodes` | GET | Get nodes with specific model |

---

## 12. Backward Compatibility

During transition:
1. Keep `OLLAMA_HOST` env var as fallback
2. If no bridge-enabled nodes have model, use fallback
3. Log when using fallback for monitoring
4. Gradually enable nodes for bridge sharing

---

**Document Status**: PLANNING
**Last Updated**: 2026-01-22
**Next Review**: After Phase 70 implementation
