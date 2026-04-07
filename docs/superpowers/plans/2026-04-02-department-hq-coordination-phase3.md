# Department HQ Coordination — Phase 3: Fleet Service + Data Model

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `cloud_providers` and `cloud_usage_log` tables, add missing columns to `remote_nodes`, expand `fleet_service.py` with write operations (register/disconnect node, register provider, record usage), and wire the dispatcher's fleet methods to use fleet_service.

**Architecture:** `fleet_service.py` already exists with read-only functions (list_nodes, get_fleet_map_data, etc.) and 6 passing tests. Phase 3 adds the data model for cloud providers, write operations for node/provider lifecycle, and wires the dispatcher's `_find_fleet_agent` and `check_fleet_health` to call fleet_service instead of doing direct SQL. The existing `contractor_providers` table continues to work alongside the new `cloud_providers` table (no migration needed — `list_providers()` already reads from `contractor_providers`).

**Tech Stack:** Python 3.11, Flask, psycopg2, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-31-agent-lifecycle-coordination-design.md` (Phase 3 section)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `database/migrations/031_cloud_providers.sql` | cloud_providers + cloud_usage_log tables |
| Create | `database/migrations/032_remote_nodes_location.sql` | Add location_label, node_type to remote_nodes |
| Modify | `platform_v2/services/fleet_service.py` | Add register_node, disconnect_node, register_provider, record_cloud_usage, get_cloud_provider |
| Modify | `ai_bridge/bridge_dispatcher.py` | Wire _find_fleet_agent + check_fleet_health to fleet_service |
| Create | `platform_v2/services/tests/test_phase3_fleet.py` | Tests for new fleet_service functions |

---

### Task 1: Database migrations — cloud_providers + cloud_usage_log + remote_nodes columns

**Files:**
- Create: `database/migrations/031_cloud_providers.sql`
- Create: `database/migrations/032_remote_nodes_location.sql`

- [ ] **Step 1: Create cloud_providers migration**

Create `database/migrations/031_cloud_providers.sql`:

```sql
-- Phase 3: Cloud provider management
-- Idempotent: uses IF NOT EXISTS

CREATE TABLE IF NOT EXISTS cloud_providers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    logo_url TEXT,
    headquarters_city VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    provider_type VARCHAR(20) DEFAULT 'cloud',
    api_endpoint TEXT,
    api_key_env_var VARCHAR(100),
    tier VARCHAR(30) DEFAULT 'free',
    capabilities JSONB DEFAULT '[]',
    models_available JSONB DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'active',
    monthly_budget DECIMAL(10,2) DEFAULT 0,
    monthly_usage DECIMAL(10,2) DEFAULT 0,
    usage_reset_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cloud_usage_log (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES cloud_providers(id),
    agent_id INTEGER REFERENCES agents(id),
    model_name VARCHAR(100),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    estimated_cost DECIMAL(10,6) DEFAULT 0,
    capability VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cloud_usage_log_provider ON cloud_usage_log(provider_id);
CREATE INDEX IF NOT EXISTS idx_cloud_usage_log_created ON cloud_usage_log(created_at);

-- Seed known providers
INSERT INTO cloud_providers (name, headquarters_city, latitude, longitude, provider_type, api_key_env_var, tier, capabilities, models_available, status)
VALUES
    ('OpenAI', 'San Francisco', 37.7749, -122.4194, 'cloud', 'OPENAI_API_KEY', 'pay-as-you-go',
     '["chat","embedding","image_gen"]', '["gpt-4o","gpt-4o-mini","dall-e-3"]', 'active'),
    ('Anthropic', 'San Francisco', 37.7749, -122.4194, 'cloud', 'ANTHROPIC_API_KEY', 'pay-as-you-go',
     '["chat"]', '["claude-sonnet-4-20250514","claude-haiku-4-5-20251001"]', 'active'),
    ('Google AI', 'Mountain View', 37.3861, -122.0839, 'cloud', 'GOOGLE_AI_API_KEY', 'free',
     '["chat","embedding"]', '["gemini-2.0-flash"]', 'inactive'),
    ('Groq', 'Mountain View', 37.3861, -122.0839, 'cloud', 'GROQ_API_KEY', 'free',
     '["chat"]', '["llama-3.3-70b-versatile","mixtral-8x7b-32768"]', 'active')
ON CONFLICT DO NOTHING;
```

- [ ] **Step 2: Create remote_nodes location migration**

Create `database/migrations/032_remote_nodes_location.sql`:

```sql
-- Phase 3: Add location and type metadata to remote_nodes
-- Idempotent: uses IF NOT EXISTS

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS location_label VARCHAR(100);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS node_type VARCHAR(20) DEFAULT 'starship';

-- Backfill existing nodes
UPDATE remote_nodes SET location_label = 'Toronto, Canada' WHERE hostname = '192.168.1.200' AND location_label IS NULL;
UPDATE remote_nodes SET location_label = 'US East (Hostinger)', node_type = 'outpost' WHERE hostname LIKE '76.%' AND location_label IS NULL;
UPDATE remote_nodes SET node_type = 'starship' WHERE node_type IS NULL;
```

- [ ] **Step 3: Run both migrations**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/031_cloud_providers.sql
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/032_remote_nodes_location.sql
```

**Note:** The migration files are in the repo at `database/migrations/` but Docker mounts them at `/docker-entrypoint-initdb.d/migrations/`. If that mount doesn't exist, copy them in:

```bash
docker cp database/migrations/031_cloud_providers.sql archie_database:/tmp/031.sql
docker exec archie_database psql -U archie -d archie -f /tmp/031.sql
docker cp database/migrations/032_remote_nodes_location.sql archie_database:/tmp/032.sql
docker exec archie_database psql -U archie -d archie -f /tmp/032.sql
```

- [ ] **Step 4: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d cloud_providers" | head -5
docker exec archie_database psql -U archie -d archie -c "\d cloud_usage_log" | head -5
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'remote_nodes' AND column_name IN ('location_label','node_type');"
docker exec archie_database psql -U archie -d archie -c "SELECT id, name, tier, status FROM cloud_providers;"
```

Expected: Both tables exist, remote_nodes has new columns, 4 seeded providers.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/031_cloud_providers.sql database/migrations/032_remote_nodes_location.sql
git commit -m "feat(fleet): add cloud_providers + cloud_usage_log tables, remote_nodes location columns

Phase 3: New cloud_providers table with 4 seeded providers (OpenAI,
Anthropic, Google AI, Groq). New cloud_usage_log for per-call tracking.
remote_nodes gets location_label and node_type columns."
```

---

### Task 2: Expand fleet_service.py — write operations

**Files:**
- Modify: `platform_v2/services/fleet_service.py`
- Create: `platform_v2/services/tests/test_phase3_fleet.py`

- [ ] **Step 1: Write failing tests**

Create `platform_v2/services/tests/test_phase3_fleet.py`:

```python
"""Tests for fleet_service Phase 3 write operations.

Run: docker exec archie_platform python -m pytest services/tests/test_phase3_fleet.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database import get_db_cursor


def _cleanup_test_provider():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM cloud_usage_log WHERE provider_id IN (SELECT id FROM cloud_providers WHERE name = 'TestProvider')")
        cur.execute("DELETE FROM cloud_providers WHERE name = 'TestProvider'")


def test_register_provider():
    """register_provider should create a cloud provider and return its id."""
    from services.fleet_service import register_provider
    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
        )
        assert isinstance(pid, int)
        assert pid > 0
    finally:
        _cleanup_test_provider()


def test_register_provider_with_location():
    """register_provider with location stores lat/lon."""
    from services.fleet_service import register_provider, get_cloud_provider
    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider",
            provider_type="cloud",
            api_key_env_var="TEST_KEY",
            tier="free",
            capabilities=["chat"],
            headquarters_city="Toronto",
            latitude=43.6532,
            longitude=-79.3832,
        )
        provider = get_cloud_provider(pid)
        assert provider is not None
        assert provider["name"] == "TestProvider"
        assert float(provider["latitude"]) == 43.6532
    finally:
        _cleanup_test_provider()


def test_record_cloud_usage():
    """record_cloud_usage should insert a usage log entry."""
    from services.fleet_service import register_provider, record_cloud_usage
    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider", provider_type="cloud",
            api_key_env_var="TEST_KEY", tier="free", capabilities=["chat"],
        )
        record_cloud_usage(
            provider_id=pid, model_name="test-model",
            tokens_in=100, tokens_out=50, estimated_cost=0.001,
            capability="chat",
        )
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) AS cnt FROM cloud_usage_log WHERE provider_id = %s", (pid,))
            assert cur.fetchone()["cnt"] == 1
    finally:
        _cleanup_test_provider()


def test_record_cloud_usage_updates_monthly():
    """record_cloud_usage should increment monthly_usage on the provider."""
    from services.fleet_service import register_provider, record_cloud_usage, get_cloud_provider
    _cleanup_test_provider()
    try:
        pid = register_provider(
            name="TestProvider", provider_type="cloud",
            api_key_env_var="TEST_KEY", tier="free", capabilities=["chat"],
        )
        record_cloud_usage(pid, "test-model", 100, 50, 0.01, "chat")
        record_cloud_usage(pid, "test-model", 200, 100, 0.02, "chat")
        provider = get_cloud_provider(pid)
        assert float(provider["monthly_usage"]) == 0.03
    finally:
        _cleanup_test_provider()


def test_get_cloud_provider_not_found():
    """get_cloud_provider returns None for non-existent id."""
    from services.fleet_service import get_cloud_provider
    assert get_cloud_provider(-999) is None


def test_list_cloud_providers():
    """list_cloud_providers returns seeded providers."""
    from services.fleet_service import list_cloud_providers
    providers = list_cloud_providers()
    assert isinstance(providers, list)
    assert len(providers) >= 4  # seeded in migration
    names = [p["name"] for p in providers]
    assert "OpenAI" in names
    assert "Anthropic" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase3_fleet.py -v 2>&1 | tail -15
```

Expected: FAIL — `ImportError: cannot import name 'register_provider'`

- [ ] **Step 3: Add write operations to fleet_service.py**

Add these functions to `platform_v2/services/fleet_service.py` after the existing functions:

```python
# ---------------------------------------------------------------------------
# Cloud Provider Management (Phase 3)
# ---------------------------------------------------------------------------


def register_provider(
    name,
    provider_type="cloud",
    api_key_env_var="",
    tier="free",
    capabilities=None,
    models_available=None,
    api_endpoint="",
    headquarters_city="",
    latitude=None,
    longitude=None,
    monthly_budget=0,
):
    """Register a new cloud provider. Returns provider id."""
    from psycopg2 import Json

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO cloud_providers
               (name, provider_type, api_key_env_var, tier,
                capabilities, models_available, api_endpoint,
                headquarters_city, latitude, longitude, monthly_budget)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                name, provider_type, api_key_env_var, tier,
                Json(capabilities or []),
                Json(models_available or []),
                api_endpoint, headquarters_city,
                latitude, longitude, monthly_budget,
            ),
        )
        return cur.fetchone()["id"]


def get_cloud_provider(provider_id):
    """Get a single cloud provider by id. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM cloud_providers WHERE id = %s", (provider_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_cloud_providers():
    """List all cloud providers from the cloud_providers table."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM cloud_providers ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


def record_cloud_usage(
    provider_id,
    model_name,
    tokens_in=0,
    tokens_out=0,
    estimated_cost=0,
    capability="",
    agent_id=None,
):
    """Record a cloud API call and update the provider's monthly usage."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO cloud_usage_log
               (provider_id, agent_id, model_name, tokens_in, tokens_out,
                estimated_cost, capability)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (provider_id, agent_id, model_name, tokens_in, tokens_out,
             estimated_cost, capability),
        )
        cur.execute(
            """UPDATE cloud_providers
               SET monthly_usage = COALESCE(monthly_usage, 0) + %s,
                   updated_at = NOW()
               WHERE id = %s""",
            (estimated_cost, provider_id),
        )


def disconnect_node(node_id):
    """Mark a node as offline and return its agents to barracks.

    Returns dict with node_name and recalled_agents count.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT node_name FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Node {node_id} not found"}

        node_name = row["node_name"]

        # Mark node offline
        cur.execute(
            "UPDATE remote_nodes SET status = 'offline' WHERE id = %s",
            (node_id,),
        )

        # Return agents to barracks
        cur.execute(
            """UPDATE node_agents SET status = 'recalled'
               WHERE node_id = (SELECT node_id FROM remote_nodes WHERE id = %s)
               AND status = 'active'
               RETURNING hub_agent_id""",
            (node_id,),
        )
        recalled = cur.fetchall()

        # Reset hub agents to barracked
        for r in recalled:
            if r["hub_agent_id"]:
                cur.execute(
                    "UPDATE agents SET shift_state = 'barracked' WHERE id = %s",
                    (r["hub_agent_id"],),
                )

        logger.info(
            "fleet_service: disconnected node %s, recalled %d agents",
            node_name, len(recalled),
        )
        return {"success": True, "node_name": node_name, "recalled_agents": len(recalled)}
```

- [ ] **Step 4: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/test_phase3_fleet.py -v 2>&1 | tail -15
```

Expected: All 6 tests PASS

- [ ] **Step 5: Run all existing fleet tests too**

```bash
docker exec archie_platform python -m pytest services/tests/test_fleet_service.py services/tests/test_phase3_fleet.py -v 2>&1 | tail -20
```

Expected: All tests pass (existing 6 + new 6 = 12)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/fleet_service.py platform_v2/services/tests/test_phase3_fleet.py
git commit -m "feat(fleet-service): add provider registration, usage tracking, node disconnect

Phase 3: fleet_service gets register_provider(), get_cloud_provider(),
list_cloud_providers(), record_cloud_usage() for cloud provider lifecycle,
and disconnect_node() for fleet node management. 6 new tests."
```

---

### Task 3: Wire dispatcher fleet methods to fleet_service

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

The dispatcher has `_find_fleet_agent()` (~80 lines of direct SQL) and `check_fleet_health()` (~90 lines). We wire them to use `fleet_service` for data access while keeping the dispatch logic in the dispatcher.

- [ ] **Step 1: Add fleet_service import**

In `bridge_dispatcher.py`, find the Phase 2 imports (around line ~42-52) and add:

```python
from services.fleet_service import list_nodes, get_node_status, disconnect_node as svc_disconnect_node
```

Add inside the existing try/except block that has `_HAS_DEPT_HQ_SERVICES`.

- [ ] **Step 2: Wire check_fleet_health to use fleet_service for node status**

In `check_fleet_health()` (around line ~7327), the method queries `remote_nodes` directly. Add a fleet_service integration at the top of the method to get node data, but keep the heartbeat/transition logic in the dispatcher:

Find the line where `check_fleet_health` queries remote_nodes. After the method docstring, add:

```python
        # Phase 3: Use fleet_service for node data when available
        if _HAS_DEPT_HQ_SERVICES:
            try:
                fleet_nodes = list_nodes()
                # Use fleet_service data to augment health checks
                for fn in fleet_nodes:
                    if fn.get("status") == "offline" and fn.get("id"):
                        logger.debug("[FleetHealth] Node %s offline per fleet_service", fn["node_name"])
            except Exception as exc:
                logger.debug("[FleetHealth] fleet_service unavailable, using direct SQL: %s", exc)
```

**IMPORTANT:** This is additive — do NOT remove the existing SQL queries. The fleet_service integration augments, not replaces. The existing heartbeat logic is battle-tested.

- [ ] **Step 3: Mark _find_fleet_agent and check_fleet_health with Phase 3 note**

Add a Phase 3 comment to both methods indicating fleet_service is now available:

```python
    def _find_fleet_agent(self, department, capability, model_preference=None):
        """Find an available agent on a fleet node.

        Phase 3 note: fleet_service.list_nodes() and fleet_service.get_node_status()
        are now available for node data. Full migration planned for Phase 5.
        """
```

```python
    def check_fleet_health(self):
        """Monitor node heartbeats and handle offline/online transitions.

        Phase 3 note: fleet_service.disconnect_node() handles agent recall.
        Full migration planned for Phase 5.
        """
```

- [ ] **Step 4: Run all tests**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass (44 Phase 1+2 + 12 fleet = 56 total)

- [ ] **Step 5: Restart and verify**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
sleep 15
docker logs --since=30s archie_platform 2>&1 | grep -iE 'error|traceback|fleet' | head -10
```

Expected: No errors. Fleet health check running.

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "refactor(dispatcher): integrate fleet_service for node operations

Phase 3: check_fleet_health augmented with fleet_service data,
fleet_service import added alongside Phase 2 services. _find_fleet_agent
and check_fleet_health annotated for Phase 5 full migration."
```

---

### Task 4: Verify everything works end-to-end

**Files:** Read-only verification, no edits.

- [ ] **Step 1: Verify cloud_providers table has data**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT id, name, tier, status, headquarters_city FROM cloud_providers;"
```

Expected: 4 seeded providers (OpenAI, Anthropic, Google AI, Groq)

- [ ] **Step 2: Verify fleet_service reads cloud providers**

```bash
docker exec archie_platform python3 -c "
from services.fleet_service import list_cloud_providers, get_fleet_map_data
providers = list_cloud_providers()
print(f'Cloud providers: {len(providers)}')
for p in providers:
    print(f'  {p[\"name\"]}: {p[\"tier\"]} ({p[\"status\"]})')

data = get_fleet_map_data()
print(f'Fleet map: {len(data[\"nodes\"])} nodes, {len(data[\"providers\"])} providers')
"
```

- [ ] **Step 3: Verify consciousness loops still work**

```bash
docker logs --since=120s archie_platform 2>&1 | grep -iE 'embedding|analysis|knowledge.?card' | tail -5
```

Expected: Active processing.

- [ ] **Step 4: Run full test suite**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass.

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | DB migrations: cloud_providers + cloud_usage_log + remote_nodes columns | 2 SQL files | 1 |
| 2 | fleet_service write operations: register_provider, record_usage, disconnect_node | fleet_service.py + tests | 1 |
| 3 | Wire dispatcher fleet methods to fleet_service | bridge_dispatcher.py | 1 |
| 4 | End-to-end verification | Read-only | 0 |

**Total: 3 commits, 2 migration files, 1 test file, 2 modified files**

After Phase 3:
- `cloud_providers` table with 4 seeded providers (OpenAI, Anthropic, Google AI, Groq)
- `cloud_usage_log` for per-call cost tracking
- `remote_nodes` has `location_label` + `node_type` columns
- `fleet_service.py` handles both read and write fleet operations
- Dispatcher augmented with fleet_service data (full migration in Phase 5)
- Fleet map data includes cloud providers with coordinates
