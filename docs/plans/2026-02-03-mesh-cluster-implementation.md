# A.R.C.H.I.E. Mesh Cluster Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement Phase A (Hub Preparation) of the mesh cluster architecture — add DEPLOYMENT_MODE support, create mesh API endpoints, Hub Bridge template, and hub-level database tables so the Hub can orchestrate business nodes.

**Architecture:** The Hub (192.168.1.200) gets a `DEPLOYMENT_MODE=hub` env var. New mesh API endpoints handle node registration with full-stack deployment info, inter-node sync protocol, and agent lending. A new `bridge_hub.html` template gives ARCHIE a cluster-wide view distinct from the existing per-node Bridge. New database tables (`mesh_code_versions`, `mesh_learning_patterns`, `mesh_agent_loans`) extend the existing schema from migrations 069/070.

**Tech Stack:** Flask/Blueprints, PostgreSQL 16, psycopg2, Jinja2, Docker Compose, existing `get_db_cursor()` pattern from `database.py`.

**Design doc:** `docs/plans/2026-02-03-archie-mesh-cluster-design.md`

---

## Context for the Implementer

### Codebase Patterns

**Database access** — always use the context manager pattern:
```python
from database import get_db_cursor
from psycopg2.extras import RealDictCursor

with get_db_cursor() as (conn, cur):
    cur.execute("SELECT * FROM remote_nodes WHERE status = %s", ('online',))
    rows = cur.fetchall()
# Auto-commits, auto-releases connection to pool
```

**Blueprint routes** — the bridge blueprint is at `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`:
```python
bridge_bp = Blueprint("bridge", __name__, url_prefix="/tools/bridge")

@bridge_bp.route("/api/nodes")
def get_all_nodes():
    ...
```

**Auth** — node API key auth uses `X-Node-API-Key` header, verified via SHA256 hash comparison. Admin routes use `@login_required` + `@admin_required` decorators.

**Config** — `/mnt/archie_brain/platform_v2/config.py` has a `Config` class with env var defaults. Two `.env` files: root and `platform_v2/.env`.

**Templates** — live at `/mnt/archie_brain/platform_v2/templates/tools/`. Bridge dashboard is `bridge.html`. Admin nav shared component is at `templates/includes/admin_ops_nav.html`.

**Migrations** — sequential numbered SQL files in `/mnt/archie_brain/database/migrations/`. Latest is 075. Next available: **076**.

### What Already Exists

| Component | Status | Location |
|-----------|--------|----------|
| Node registration API | Working | `bridge/routes.py:2273-2391` |
| Node heartbeat API | Working | `bridge/routes.py:2393-2527` |
| Node approval workflow | Working | `bridge/routes.py` |
| `get_all_nodes()` with org JOIN | Working | `bridge/routes.py:2041-2117` |
| `remote_nodes` table | Exists | migration 067 |
| `node_ollama_models` table | Exists | migration 070 |
| `node_namespaces` table | Exists | migration 069 |
| `node_station_assignments` table | Exists | migration 069 |
| `node_iaae_attestations` table | Exists | migration 069 |
| `archie_migrations` table | Exists | migration 069 |
| Node router (weighted selection) | Working | `ai_bridge/node_router.py` |
| SaaS Manager org-to-node API | Working | `saas_manager/saas_manager_routes.py` |
| Install scripts (Ollama-only) | Working | `node_client/install.sh`, `install.ps1` |
| Heartbeat scripts | Working | `node_client/heartbeat.sh`, `heartbeat.ps1` |
| `DEPLOYMENT_MODE` env var | **Not yet added** | — |
| Hub Bridge template | **Not yet created** | — |
| Mesh sync protocol endpoints | **Not yet created** | — |
| `mesh_code_versions` table | **Not yet created** | — |
| `mesh_learning_patterns` table | **Not yet created** | — |
| `mesh_agent_loans` table | **Not yet created** | — |

### Important File Paths

```
/mnt/archie_brain/platform_v2/config.py                              - Config class
/mnt/archie_brain/platform_v2/database.py                            - get_db_cursor()
/mnt/archie_brain/platform_v2/app.py                                 - Blueprint registration
/mnt/archie_brain/platform_v2/tools/bridge/routes.py                 - Bridge routes (5,774 lines)
/mnt/archie_brain/platform_v2/templates/tools/bridge.html            - Current Bridge template
/mnt/archie_brain/platform_v2/templates/includes/admin_ops_nav.html  - Shared admin nav
/mnt/archie_brain/ai_bridge/node_router.py                           - LLM routing
/mnt/archie_brain/database/migrations/                               - SQL migrations
/mnt/archie_brain/.env                                               - Root env file
/mnt/archie_brain/platform_v2/.env                                   - Platform env file
/mnt/archie_brain/docker-compose.yml                                 - Docker services
```

---

## Task 1: Add DEPLOYMENT_MODE to Config and Environment

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/config.py:10` (inside Config class)
- Modify: `/mnt/archie_brain/.env`
- Modify: `/mnt/archie_brain/platform_v2/.env`
- Modify: `/mnt/archie_brain/docker-compose.yml`

**Step 1: Add DEPLOYMENT_MODE to Config class**

In `/mnt/archie_brain/platform_v2/config.py`, add after line 16 (after `DEBUG = ...`):

```python
    # Deployment Mode: 'hub' for ARCHIE Hub, 'business_node' for business instances
    DEPLOYMENT_MODE = os.getenv('DEPLOYMENT_MODE', 'hub')
```

**Step 2: Add DEPLOYMENT_MODE to both .env files**

Add to `/mnt/archie_brain/.env`:
```
DEPLOYMENT_MODE=hub
```

Add to `/mnt/archie_brain/platform_v2/.env`:
```
DEPLOYMENT_MODE=hub
```

**Step 3: Add DEPLOYMENT_MODE to docker-compose.yml**

In `/mnt/archie_brain/docker-compose.yml`, in the `archie_platform` service environment section, add:
```yaml
      DEPLOYMENT_MODE: ${DEPLOYMENT_MODE:-hub}
```

**Step 4: Verify**

```bash
docker exec archie_platform python3 -c "import os; print('DEPLOYMENT_MODE:', os.getenv('DEPLOYMENT_MODE', 'not set'))"
```

Expected: `DEPLOYMENT_MODE: hub` (after container restart)

**Step 5: Commit**

```bash
git add platform_v2/config.py .env platform_v2/.env docker-compose.yml
git commit -m "feat(mesh): add DEPLOYMENT_MODE env var for hub/node distinction"
```

---

## Task 2: Database Migration 076 — Mesh Hub Tables

**Files:**
- Create: `/mnt/archie_brain/database/migrations/076_mesh_hub_tables.sql`

**Step 1: Write the migration**

Create `/mnt/archie_brain/database/migrations/076_mesh_hub_tables.sql`:

```sql
-- Migration 076: Mesh Hub Tables
-- Date: 2026-02-03
-- Phase: Hub Preparation for Mesh Cluster Architecture
-- Description: Adds hub-level tables for code versioning, learning patterns, agent loans, and subscriptions

-- ============================================================================
-- 1. MESH CODE VERSIONS (track what version each node runs)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_code_versions (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    version VARCHAR(50) NOT NULL,
    git_commit VARCHAR(40),
    migration_version INTEGER,
    modules_list JSONB DEFAULT '[]',
    reported_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_code_version_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    CONSTRAINT uq_code_version_node UNIQUE (node_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_code_versions_node ON mesh_code_versions(node_id);

-- ============================================================================
-- 2. MESH LEARNING PATTERNS (anonymized insights from all nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_learning_patterns (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    pattern_type VARCHAR(50) NOT NULL,
    category VARCHAR(100),
    insight TEXT NOT NULL,
    metric_name VARCHAR(100),
    metric_value FLOAT,
    metric_unit VARCHAR(50),
    context JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_learning_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_learning_node ON mesh_learning_patterns(node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_learning_type ON mesh_learning_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_mesh_learning_created ON mesh_learning_patterns(created_at);

-- ============================================================================
-- 3. MESH AGENT LOANS (track agent lending between nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_agent_loans (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    source_node_id VARCHAR(50) NOT NULL,
    target_node_id VARCHAR(50) NOT NULL,
    task_description TEXT,
    status VARCHAR(20) DEFAULT 'active',
    lent_at TIMESTAMP DEFAULT NOW(),
    returned_at TIMESTAMP,
    work_summary TEXT,
    initiated_by VARCHAR(50) DEFAULT 'archie',
    CONSTRAINT fk_loan_source FOREIGN KEY (source_node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    CONSTRAINT fk_loan_target FOREIGN KEY (target_node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_loans_source ON mesh_agent_loans(source_node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_target ON mesh_agent_loans(target_node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_status ON mesh_agent_loans(status);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_active ON mesh_agent_loans(status) WHERE status = 'active';

-- ============================================================================
-- 4. SUBSCRIPTIONS (tier, features, billing for business nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_subscriptions (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL,
    tier VARCHAR(20) NOT NULL DEFAULT 'core',
    features JSONB DEFAULT '[]',
    started_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    CONSTRAINT fk_subscription_org FOREIGN KEY (org_id)
        REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT uq_subscription_org UNIQUE (org_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_subscriptions_org ON mesh_subscriptions(org_id);
CREATE INDEX IF NOT EXISTS idx_mesh_subscriptions_tier ON mesh_subscriptions(tier);

-- ============================================================================
-- 5. ADD deployment_mode TO remote_nodes (if not exists)
-- ============================================================================

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS deployment_mode VARCHAR(30) DEFAULT 'ollama_only';

-- ============================================================================
-- 6. MESH SYNC LOG (hub tracks what was synced to each node)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_sync_log (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    sync_type VARCHAR(50) NOT NULL,
    payload JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'sent',
    sent_at TIMESTAMP DEFAULT NOW(),
    acknowledged_at TIMESTAMP,
    error_message TEXT,
    CONSTRAINT fk_sync_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_sync_node ON mesh_sync_log(node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_sync_type ON mesh_sync_log(sync_type);

-- ============================================================================
-- 7. HELPER VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_mesh_cluster_overview AS
SELECT
    rn.node_id,
    rn.node_name,
    rn.vpn_ip,
    rn.status,
    rn.approval_status,
    rn.deployment_mode,
    rn.gpu_model,
    rn.gpu_vram_gb,
    rn.cpu_cores,
    rn.ram_gb,
    rn.current_load,
    rn.max_concurrent,
    rn.bridge_enabled,
    rn.last_heartbeat,
    o.name AS org_name,
    o.id AS org_id,
    ms.tier AS subscription_tier,
    mcv.version AS code_version,
    mcv.git_commit,
    (SELECT COUNT(*) FROM node_ollama_models nom WHERE nom.node_id = rn.node_id) AS model_count,
    (SELECT COUNT(*) FROM mesh_agent_loans mal WHERE mal.source_node_id = rn.node_id AND mal.status = 'active') AS agents_lent,
    (SELECT COUNT(*) FROM mesh_agent_loans mal WHERE mal.target_node_id = rn.node_id AND mal.status = 'active') AS agents_borrowed
FROM remote_nodes rn
LEFT JOIN organizations o ON o.node_id = rn.node_id
LEFT JOIN mesh_subscriptions ms ON ms.org_id = o.id
LEFT JOIN mesh_code_versions mcv ON mcv.node_id = rn.node_id
WHERE rn.is_active = true AND rn.approval_status = 'approved';

CREATE OR REPLACE VIEW v_mesh_agent_availability AS
SELECT
    mal.id AS loan_id,
    mal.agent_id,
    mal.source_node_id,
    sn.node_name AS source_node_name,
    mal.target_node_id,
    tn.node_name AS target_node_name,
    mal.task_description,
    mal.status,
    mal.lent_at,
    mal.returned_at
FROM mesh_agent_loans mal
JOIN remote_nodes sn ON sn.node_id = mal.source_node_id
JOIN remote_nodes tn ON tn.node_id = mal.target_node_id;
```

**Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/076_mesh_hub_tables.sql
```

Expected: `CREATE TABLE` / `CREATE INDEX` / `CREATE VIEW` for each statement, no errors.

**Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt mesh_*"
```

Expected output should list: `mesh_code_versions`, `mesh_learning_patterns`, `mesh_agent_loans`, `mesh_subscriptions`, `mesh_sync_log`

**Step 4: Commit**

```bash
git add database/migrations/076_mesh_hub_tables.sql
git commit -m "feat(mesh): add migration 076 — hub tables for code versions, learning, agent loans, subscriptions"
```

---

## Task 3: Mesh API Endpoints — Sync Protocol

**Files:**
- Create: `/mnt/archie_brain/platform_v2/tools/bridge/mesh_routes.py`
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py` (import + register at bottom)

This task creates a new file for mesh-specific API endpoints, keeping them organized separately from the already-large `routes.py`.

**Step 1: Create mesh_routes.py**

Create `/mnt/archie_brain/platform_v2/tools/bridge/mesh_routes.py`:

```python
"""
A.R.C.H.I.E. Mesh Cluster API Routes
=====================================
Hub-side endpoints for the mesh cluster protocol.
These handle inter-node communication: sync, agent lending,
code version tracking, learning patterns, and IAAE compliance.

Mounted on the bridge blueprint at /tools/bridge/api/mesh/*
"""

import json
import hashlib
import logging
from flask import jsonify, request
from flask_login import login_required
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _get_db_cursor():
    """Import get_db_cursor at call time to avoid circular imports."""
    import sys
    if '/mnt/archie_brain/platform_v2' not in sys.path:
        sys.path.insert(0, '/mnt/archie_brain/platform_v2')
    from database import get_db_cursor
    return get_db_cursor


def _verify_node_api_key(node_id):
    """
    Verify X-Node-API-Key header against stored hash for given node_id.
    Returns (True, node_row) on success, (False, error_msg) on failure.
    """
    api_key = request.headers.get('X-Node-API-Key')
    if not api_key:
        return False, "Missing X-Node-API-Key header"

    get_db_cursor = _get_db_cursor()
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT * FROM remote_nodes WHERE node_id = %s AND is_active = true",
            (node_id,)
        )
        node = cur.fetchone()

    if not node:
        return False, "Node not found"

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if key_hash != node.get('api_key_hash'):
        return False, "Invalid API key"

    if node.get('approval_status') != 'approved':
        return False, "Node not approved"

    return True, node


def register_mesh_routes(bridge_bp):
    """Register all mesh API routes on the bridge blueprint."""

    # ================================================================
    # VERSION REPORTING
    # ================================================================

    @bridge_bp.route("/api/mesh/version", methods=["POST"])
    def mesh_report_version():
        """Node reports its current code version to the Hub."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        node_id = data.get('node_id')
        if not node_id:
            return jsonify({"success": False, "error": "node_id required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        version = data.get('version', 'unknown')
        git_commit = data.get('git_commit')
        migration_version = data.get('migration_version')
        modules_list = data.get('modules_list', [])

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    INSERT INTO mesh_code_versions
                        (node_id, version, git_commit, migration_version, modules_list)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (node_id) DO UPDATE SET
                        version = EXCLUDED.version,
                        git_commit = EXCLUDED.git_commit,
                        migration_version = EXCLUDED.migration_version,
                        modules_list = EXCLUDED.modules_list,
                        updated_at = NOW()
                    RETURNING id
                """, (node_id, version, git_commit, migration_version,
                      json.dumps(modules_list)))
                row = cur.fetchone()

            return jsonify({"success": True, "id": row['id']})
        except Exception as e:
            logger.error(f"Mesh version report error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ================================================================
    # LEARNING PATTERNS
    # ================================================================

    @bridge_bp.route("/api/mesh/learning", methods=["POST"])
    def mesh_submit_learning():
        """Node submits an anonymized learning pattern to the Hub."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        node_id = data.get('node_id')
        if not node_id:
            return jsonify({"success": False, "error": "node_id required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        insight = data.get('insight')
        if not insight:
            return jsonify({"success": False, "error": "insight required"}), 400

        pattern_type = data.get('pattern_type', 'general')
        category = data.get('category')

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    INSERT INTO mesh_learning_patterns
                        (node_id, pattern_type, category, insight,
                         metric_name, metric_value, metric_unit, context)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                """, (
                    node_id, pattern_type, category, insight,
                    data.get('metric_name'), data.get('metric_value'),
                    data.get('metric_unit'),
                    json.dumps(data.get('context', {}))
                ))
                row = cur.fetchone()

            return jsonify({"success": True, "id": row['id']})
        except Exception as e:
            logger.error(f"Mesh learning submit error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/learning", methods=["GET"])
    @login_required
    def mesh_get_learnings():
        """Hub admin views aggregated learning patterns."""
        try:
            limit = request.args.get('limit', 50, type=int)
            pattern_type = request.args.get('type')

            get_db_cursor = _get_db_cursor()
            with get_db_cursor(commit=False) as (conn, cur):
                query = """
                    SELECT mlp.*, rn.node_name
                    FROM mesh_learning_patterns mlp
                    JOIN remote_nodes rn ON rn.node_id = mlp.node_id
                """
                params = []
                if pattern_type:
                    query += " WHERE mlp.pattern_type = %s"
                    params.append(pattern_type)
                query += " ORDER BY mlp.created_at DESC LIMIT %s"
                params.append(limit)

                cur.execute(query, params)
                patterns = cur.fetchall()

            for p in patterns:
                if p.get('created_at'):
                    p['created_at'] = p['created_at'].isoformat()

            return jsonify({"success": True, "patterns": patterns, "count": len(patterns)})
        except Exception as e:
            logger.error(f"Mesh get learnings error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ================================================================
    # AGENT LENDING
    # ================================================================

    @bridge_bp.route("/api/mesh/agents/lend", methods=["POST"])
    @login_required
    def mesh_lend_agent():
        """ARCHIE (Hub admin) lends an agent from one node to another."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        agent_id = data.get('agent_id')
        source_node_id = data.get('source_node_id')
        target_node_id = data.get('target_node_id')
        task_description = data.get('task_description')

        if not all([agent_id, source_node_id, target_node_id]):
            return jsonify({
                "success": False,
                "error": "agent_id, source_node_id, target_node_id required"
            }), 400

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    SELECT node_id FROM remote_nodes
                    WHERE node_id IN (%s, %s) AND approval_status = 'approved'
                """, (source_node_id, target_node_id))
                found = [r['node_id'] for r in cur.fetchall()]
                if source_node_id not in found:
                    return jsonify({
                        "success": False,
                        "error": "Source node not found or not approved"
                    }), 404
                if target_node_id not in found:
                    return jsonify({
                        "success": False,
                        "error": "Target node not found or not approved"
                    }), 404

                cur.execute("""
                    INSERT INTO mesh_agent_loans
                        (agent_id, source_node_id, target_node_id,
                         task_description, initiated_by)
                    VALUES (%s, %s, %s, %s, 'archie')
                    RETURNING id
                """, (agent_id, source_node_id, target_node_id, task_description))
                row = cur.fetchone()

            return jsonify({"success": True, "loan_id": row['id']})
        except Exception as e:
            logger.error(f"Mesh agent lend error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/agents/return", methods=["POST"])
    def mesh_return_agent():
        """Node returns a borrowed agent with work summary."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        loan_id = data.get('loan_id')
        node_id = data.get('node_id')
        work_summary = data.get('work_summary', '')

        if not loan_id or not node_id:
            return jsonify({
                "success": False,
                "error": "loan_id and node_id required"
            }), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    UPDATE mesh_agent_loans
                    SET status = 'completed',
                        returned_at = NOW(),
                        work_summary = %s
                    WHERE id = %s AND target_node_id = %s AND status = 'active'
                    RETURNING id
                """, (work_summary, loan_id, node_id))
                row = cur.fetchone()

            if not row:
                return jsonify({
                    "success": False,
                    "error": "Loan not found or not active"
                }), 404
            return jsonify({"success": True, "loan_id": row['id']})
        except Exception as e:
            logger.error(f"Mesh agent return error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/agents/loans", methods=["GET"])
    @login_required
    def mesh_get_loans():
        """Hub admin views active agent loans across the mesh."""
        try:
            status_filter = request.args.get('status', 'active')

            get_db_cursor = _get_db_cursor()
            with get_db_cursor(commit=False) as (conn, cur):
                query = """
                    SELECT mal.*,
                           sn.node_name AS source_name,
                           tn.node_name AS target_name
                    FROM mesh_agent_loans mal
                    JOIN remote_nodes sn ON sn.node_id = mal.source_node_id
                    JOIN remote_nodes tn ON tn.node_id = mal.target_node_id
                """
                params = []
                if status_filter != 'all':
                    query += " WHERE mal.status = %s"
                    params.append(status_filter)
                query += " ORDER BY mal.lent_at DESC LIMIT 100"

                cur.execute(query, params)
                loans = cur.fetchall()

            for loan in loans:
                for key in ['lent_at', 'returned_at']:
                    if loan.get(key):
                        loan[key] = loan[key].isoformat()

            return jsonify({
                "success": True,
                "loans": loans,
                "count": len(loans)
            })
        except Exception as e:
            logger.error(f"Mesh get loans error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ================================================================
    # SYNC LOG
    # ================================================================

    @bridge_bp.route("/api/mesh/sync", methods=["POST"])
    @login_required
    def mesh_push_sync():
        """Hub pushes a sync command to a node (logged in mesh_sync_log)."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "JSON body required"}), 400

        node_id = data.get('node_id')
        sync_type = data.get('sync_type')
        payload = data.get('payload', {})

        if not node_id or not sync_type:
            return jsonify({
                "success": False,
                "error": "node_id and sync_type required"
            }), 400

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    INSERT INTO mesh_sync_log (node_id, sync_type, payload)
                    VALUES (%s, %s, %s::jsonb)
                    RETURNING id
                """, (node_id, sync_type, json.dumps(payload)))
                row = cur.fetchone()

            return jsonify({"success": True, "sync_id": row['id']})
        except Exception as e:
            logger.error(f"Mesh sync push error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/sync/<node_id>/pending", methods=["GET"])
    def mesh_get_pending_syncs(node_id):
        """Node polls for pending sync commands from the Hub."""
        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("""
                    SELECT id, sync_type, payload, sent_at
                    FROM mesh_sync_log
                    WHERE node_id = %s AND status = 'sent'
                    ORDER BY sent_at ASC
                """, (node_id,))
                syncs = cur.fetchall()

            for s in syncs:
                if s.get('sent_at'):
                    s['sent_at'] = s['sent_at'].isoformat()

            return jsonify({
                "success": True,
                "syncs": syncs,
                "count": len(syncs)
            })
        except Exception as e:
            logger.error(f"Mesh get pending syncs error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bridge_bp.route("/api/mesh/sync/<int:sync_id>/ack", methods=["POST"])
    def mesh_ack_sync(sync_id):
        """Node acknowledges a sync command."""
        data = request.get_json() or {}
        node_id = data.get('node_id')

        if not node_id:
            return jsonify({"success": False, "error": "node_id required"}), 400

        valid, result = _verify_node_api_key(node_id)
        if not valid:
            return jsonify({"success": False, "error": result}), 403

        status = data.get('status', 'acknowledged')
        error_message = data.get('error_message')

        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor() as (conn, cur):
                cur.execute("""
                    UPDATE mesh_sync_log
                    SET status = %s,
                        acknowledged_at = NOW(),
                        error_message = %s
                    WHERE id = %s AND node_id = %s
                    RETURNING id
                """, (status, error_message, sync_id, node_id))
                row = cur.fetchone()

            if not row:
                return jsonify({
                    "success": False,
                    "error": "Sync entry not found"
                }), 404
            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Mesh sync ack error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ================================================================
    # CLUSTER OVERVIEW (Hub admin only)
    # ================================================================

    @bridge_bp.route("/api/mesh/cluster", methods=["GET"])
    @login_required
    def mesh_cluster_overview():
        """Hub admin gets full cluster overview from the view."""
        try:
            get_db_cursor = _get_db_cursor()
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT * FROM v_mesh_cluster_overview ORDER BY node_name"
                )
                nodes = cur.fetchall()

                cur.execute("""
                    SELECT
                        COUNT(*) AS total_nodes,
                        COUNT(*) FILTER (WHERE status = 'online') AS online_nodes,
                        SUM(current_load) AS total_load,
                        SUM(max_concurrent) AS total_capacity,
                        SUM(model_count) AS total_models,
                        SUM(agents_lent) AS total_agents_lent
                    FROM v_mesh_cluster_overview
                """)
                stats = cur.fetchone()

            for n in nodes:
                if n.get('last_heartbeat'):
                    n['last_heartbeat'] = n['last_heartbeat'].isoformat()

            return jsonify({
                "success": True,
                "nodes": nodes,
                "stats": stats
            })
        except Exception as e:
            logger.error(f"Mesh cluster overview error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    logger.info("Mesh API routes registered")
```

**Step 2: Register mesh routes in bridge/routes.py**

At the **bottom** of `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`, add:

```python
# ============================================================================
# MESH CLUSTER API ROUTES
# ============================================================================
try:
    from tools.bridge.mesh_routes import register_mesh_routes
    register_mesh_routes(bridge_bp)
except ImportError as e:
    logger.warning(f"Mesh routes not loaded: {e}")
```

**Step 3: Verify the import works**

```bash
docker compose restart archie_platform && sleep 5 && docker logs archie_platform 2>&1 | tail -20
```

Expected: No import errors. Should see "Mesh API routes registered" in logs.

**Step 4: Test an endpoint**

```bash
curl -s http://192.168.1.200:3000/tools/bridge/api/mesh/cluster | python3 -m json.tool | head -20
```

Expected: JSON response (may require login cookie, but should not 500).

**Step 5: Commit**

```bash
git add platform_v2/tools/bridge/mesh_routes.py platform_v2/tools/bridge/routes.py
git commit -m "feat(mesh): add mesh API endpoints — sync protocol, agent lending, cluster overview"
```

---

## Task 4: Hub Bridge Command Template

**Files:**
- Create: `/mnt/archie_brain/platform_v2/templates/tools/bridge_hub.html`
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py:203-205` (bridge_dashboard function)

This creates the Hub-specific Bridge Command view that shows cluster-wide info instead of a single node's view.

**Step 1: Modify bridge_dashboard() to check DEPLOYMENT_MODE**

In `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`, find the `bridge_dashboard()` function (line 203). Change it from:

```python
def bridge_dashboard():
    """Render the main Bridge command center"""
    return render_template("tools/bridge.html")
```

To:

```python
def bridge_dashboard():
    """Render the main Bridge command center"""
    deployment_mode = os.getenv('DEPLOYMENT_MODE', 'hub')
    if deployment_mode == 'hub':
        return render_template("tools/bridge_hub.html")
    else:
        return render_template("tools/bridge.html")
```

**Step 2: Create bridge_hub.html**

Create `/mnt/archie_brain/platform_v2/templates/tools/bridge_hub.html` — the full Hub Bridge Command interface with cluster map, agent lending panel, code versions, and learning feed. Uses the existing admin_ops_nav.html include. All dynamic content rendered via `textContent` or DOM element creation for XSS safety. Auto-refreshes every 30 seconds via fetch to `/tools/bridge/api/mesh/cluster` and `/tools/bridge/api/nodes`.

The template should:
- Extend `base.html`
- Include `includes/admin_ops_nav.html`
- Have sections: Cluster Stats, Node Grid, Agent Mesh Pool, Code Versions, Learning Patterns
- Use `fetch()` to load data from mesh API endpoints
- Use `document.createElement` and `textContent` for dynamic content (not innerHTML with user data)
- Match the ARCHIE dark theme: Orbitron headings, JetBrains Mono body, amber (#FFAA00) accents, green (#00FF41) for online status
- Include light mode overrides with `body.light-mode` selectors
- Responsive grid layout

**Step 3: Verify the Hub Bridge renders**

```bash
docker compose restart archie_platform && sleep 5
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge
```

Expected: `200` (or `302` redirect to login — either is fine, no 500).

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge_hub.html platform_v2/tools/bridge/routes.py
git commit -m "feat(mesh): add Hub Bridge Command template with cluster map, agent pool, learnings"
```

---

## Task 5: Node Sync Service Scaffold

**Files:**
- Create: `/mnt/archie_brain/node_client/node_sync.py`
- Create: `/mnt/archie_brain/node_client/docker-compose.node.yml`

This creates the sync service that runs on business nodes as a Docker container, handling heartbeat, version reporting, sync polling, and model inventory.

**Step 1: Create node_sync.py**

Create `/mnt/archie_brain/node_client/node_sync.py` — a standalone Python script (no Flask dependency) that:
- Reads config from env vars or `/etc/archie-node/config.json`
- Sends heartbeat to Hub every 30 seconds (POST to `/tools/bridge/api/nodes/<node_id>/heartbeat`)
- Reports code version on startup (POST to `/tools/bridge/api/mesh/version`)
- Polls for pending sync commands every 60 seconds (GET `/tools/bridge/api/mesh/sync/<node_id>/pending`)
- Handles sync commands: code_update, iaae_policy, model_recommend (stubs for now)
- Acknowledges sync commands (POST `/tools/bridge/api/mesh/sync/<sync_id>/ack`)
- Collects system metrics: CPU via `/proc/loadavg`, RAM via `/proc/meminfo`, GPU via `nvidia-smi`
- Gets Ollama model list via `GET http://localhost:11434/api/tags`
- Uses `requests` if available, falls back to `urllib`

**Step 2: Create docker-compose.node.yml**

Create `/mnt/archie_brain/node_client/docker-compose.node.yml` — Docker Compose template for business nodes with 4 services:
- `node_database`: postgres:16-alpine with health check
- `node_platform`: archie-platform image with DEPLOYMENT_MODE=business_node
- `node_ollama`: ollama/ollama with GPU passthrough
- `node_sync`: python:3.11-slim running node_sync.py

All services on a shared `archie_node` bridge network. Environment variables from `.env` file.

**Step 3: Verify syntax**

```bash
cd /mnt/archie_brain/node_client && python3 -c "import ast; ast.parse(open('node_sync.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

**Step 4: Commit**

```bash
git add node_client/node_sync.py node_client/docker-compose.node.yml
git commit -m "feat(mesh): add node sync service and business node docker-compose template"
```

---

## Task 6: Serve Docker Compose and Sync Service from Hub

**Files:**
- Modify: `/mnt/archie_brain/platform_v2/tools/bridge/routes.py` (add 2 serve endpoints)

**Step 1: Add serving endpoints**

Find the existing `get_node_install_script()` function in `routes.py` (around line 2120). After the existing install script serving block, add two new routes to serve `docker-compose.node.yml` and `node_sync.py`:

```python
@bridge_bp.route("/api/nodes/docker-compose.node.yml", methods=["GET"])
def get_node_docker_compose():
    """Serve the node Docker Compose template"""
    script_path = "/mnt/archie_brain/node_client/docker-compose.node.yml"
    if os.path.exists(script_path):
        with open(script_path, "r") as f:
            content = f.read()
        from flask import Response
        return Response(content, mimetype="text/yaml",
                       headers={"Content-Disposition":
                                "attachment; filename=docker-compose.node.yml"})
    return jsonify({"success": False, "error": "Docker Compose template not found"}), 404


@bridge_bp.route("/api/nodes/node_sync.py", methods=["GET"])
def get_node_sync_service():
    """Serve the node sync service script"""
    script_path = "/mnt/archie_brain/node_client/node_sync.py"
    if os.path.exists(script_path):
        with open(script_path, "r") as f:
            content = f.read()
        from flask import Response
        return Response(content, mimetype="text/x-python",
                       headers={"Content-Disposition":
                                "attachment; filename=node_sync.py"})
    return jsonify({"success": False, "error": "Sync service script not found"}), 404
```

**Step 2: Verify endpoints work**

```bash
docker compose restart archie_platform && sleep 5
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge/api/nodes/docker-compose.node.yml
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge/api/nodes/node_sync.py
```

Expected: Both return `200`.

**Step 3: Commit**

```bash
git add platform_v2/tools/bridge/routes.py
git commit -m "feat(mesh): serve docker-compose template and sync service from Hub"
```

---

## Task 7: Extend Install Scripts for Full-Stack Deployment

**Files:**
- Modify: `/mnt/archie_brain/node_client/install.sh`
- Modify: `/mnt/archie_brain/node_client/install.ps1`

The existing install scripts only install Ollama and register. They need a new "Phase 3" section after registration that:
1. Asks user to choose: Ollama-only vs Full-stack
2. If Full-stack: installs Docker + Docker Compose, NVIDIA Container Toolkit (if GPU), downloads docker-compose.node.yml and node_sync.py from Hub, generates .env, starts the Docker stack

**Step 1: Read existing install.sh**

Read the current file first to understand the structure.

**Step 2: Add full-stack deployment section to install.sh**

After the existing registration step (which saves config.json with node_id and api_key), add a deployment mode prompt and Docker stack deployment function. Key additions:
- `install_docker_stack()` function that installs Docker, NVIDIA toolkit, downloads files, generates .env, runs `docker compose up -d`
- Interactive prompt asking "1) Ollama-only  2) Full-stack"
- Uses the already-saved `NODE_ID` and `API_KEY` variables

**Step 3: Add equivalent section to install.ps1**

PowerShell version that checks for Docker Desktop, downloads files via `Invoke-WebRequest`, generates .env, runs `docker compose up -d`.

**Step 4: Verify syntax**

```bash
bash -n /mnt/archie_brain/node_client/install.sh && echo "Syntax OK"
```

**Step 5: Commit**

```bash
git add node_client/install.sh node_client/install.ps1
git commit -m "feat(mesh): extend install scripts with full-stack Docker deployment option"
```

---

## Task 8: Restart Platform and End-to-End Verification

**Files:** None (verification only)

**Step 1: Restart platform with new DEPLOYMENT_MODE**

```bash
docker compose restart archie_platform
```

**Step 2: Verify DEPLOYMENT_MODE**

```bash
docker exec archie_platform python3 -c "import os; print('MODE:', os.getenv('DEPLOYMENT_MODE', 'NOT SET'))"
```

Expected: `MODE: hub`

**Step 3: Verify migration 076 tables**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt mesh_*"
```

Expected: 5 tables listed.

**Step 4: Verify mesh API endpoints respond**

```bash
curl -s http://192.168.1.200:3000/tools/bridge/api/mesh/cluster 2>&1 | head -5
```

Expected: JSON response or login redirect (not 500).

**Step 5: Verify Hub Bridge renders**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge
```

Expected: `200` or `302`.

**Step 6: Verify node file serving**

```bash
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge/api/nodes/docker-compose.node.yml
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/bridge/api/nodes/node_sync.py
```

Expected: Both `200`.

**Step 7: Commit if any fixes were needed**

```bash
git status
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | DEPLOYMENT_MODE env var | config.py, .env (x2), docker-compose.yml |
| 2 | Migration 076 — hub tables | 076_mesh_hub_tables.sql |
| 3 | Mesh API endpoints | mesh_routes.py (new), routes.py (import) |
| 4 | Hub Bridge template | bridge_hub.html (new), routes.py (routing) |
| 5 | Node sync service | node_sync.py (new), docker-compose.node.yml (new) |
| 6 | Serve node files from Hub | routes.py (2 endpoints) |
| 7 | Full-stack install scripts | install.sh, install.ps1 |
| 8 | End-to-end verification | No files — testing only |

**Total new files:** 5 (mesh_routes.py, bridge_hub.html, node_sync.py, docker-compose.node.yml, 076_mesh_hub_tables.sql)
**Total modified files:** 6 (config.py, .env x2, docker-compose.yml, routes.py, install.sh, install.ps1)
