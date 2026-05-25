# Cluster Work Queue — Unified Design
**Dev HQ Task #3166 | Status: Design Complete | Date: 2026-05-25**

## Problem

`dispatch_pending_queue` and `bridge_jobs` are two parallel tables tracking in-flight work, with no unified view and no capacity-aware routing to fleet nodes. The Fleet tab "Dispatch panel" shows a fragmented picture. Capabilities that should route to Starship (GPU inference) or Outpost (small CPU models co-located with WTF/Watch) always end up on Hub by default.

## Architecture Decision

**Additive unified table + dual-write adapter.** `cluster_work_queue` is the new source of truth. The existing `dispatch_pending_queue` and `bridge_jobs` remain alive during a 30-day transition window — a thin adapter writes to both. The hot dispatch path in `department_dispatcher.py` (5,000+ lines) is **not touched**. After transition, legacy tables become historical archives.

This avoids a big-bang rewrite of the dispatcher while immediately enabling a unified Fleet tab view. The dual-write cost (2× INSERTs on ~dozens/minute) is acceptable.

---

## Migration SQL

**File:** `platform_v2/database/migrations/395_cluster_work_queue.sql`

Next available migration: 395 (after `394_parliament_vote_signal.sql`).

```sql
-- Migration 395: Unified cluster work queue
-- Safe to re-run (idempotent).

CREATE TABLE IF NOT EXISTS cluster_work_queue (
    id                  BIGSERIAL PRIMARY KEY,
    -- Work classification
    work_type           TEXT NOT NULL CHECK (work_type IN ('inference','generation','delegation','maintenance')),
    capability          TEXT NOT NULL,                    -- matches CAPABILITY_DEPARTMENT_MAP keys
    -- Routing
    target_node_id      INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,  -- NULL = auto-route
    assigned_node_id    INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,
    -- Status machine: pending → routing → assigned → running → completed/failed/cancelled
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','routing','assigned','running','completed','failed','cancelled')),
    priority            INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    -- Timing
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    -- Payload & result
    payload             JSONB NOT NULL DEFAULT '{}',     -- model, prompt, system_prompt, json_mode, params, images
    result              JSONB,                           -- response text, file_path, error detail
    -- Attribution
    requester           TEXT NOT NULL DEFAULT 'agent_loop'
                            CHECK (requester IN ('claude','agent_loop','user','automation','delegation')),
    agent_name          TEXT,
    agent_id            INTEGER,
    module_id           TEXT,
    source_product      TEXT,
    user_id             INTEGER,
    -- Retry
    retry_count         INTEGER NOT NULL DEFAULT 0,
    max_retries         INTEGER NOT NULL DEFAULT 3,
    -- Legacy linkage (NULL once transition complete)
    legacy_dpq_id       BIGINT,   -- dispatch_pending_queue.id
    legacy_bridge_job_id BIGINT,  -- bridge_jobs.id
    -- Callback (inherited from dispatch_pending_queue)
    callback_type       TEXT,
    callback_data       JSONB
);

CREATE INDEX IF NOT EXISTS idx_cwq_status_priority
    ON cluster_work_queue (status, priority DESC, created_at ASC)
    WHERE status IN ('pending','routing','assigned','running');

CREATE INDEX IF NOT EXISTS idx_cwq_assigned_node
    ON cluster_work_queue (assigned_node_id, status)
    WHERE assigned_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cwq_work_type_status
    ON cluster_work_queue (work_type, status, created_at);

CREATE INDEX IF NOT EXISTS idx_cwq_agent
    ON cluster_work_queue (agent_id, status)
    WHERE agent_id IS NOT NULL;
```

**File:** `platform_v2/database/migrations/396_v_cluster_queue_status.sql`

```sql
-- Migration 396: Fleet tab dispatch panel views
CREATE OR REPLACE VIEW v_cluster_queue_status AS
SELECT
    cwq.id,
    cwq.work_type,
    cwq.capability,
    cwq.status,
    cwq.priority,
    cwq.requester,
    cwq.agent_name,
    cwq.module_id,
    cwq.source_product,
    cwq.retry_count,
    cwq.created_at,
    cwq.started_at,
    cwq.completed_at,
    EXTRACT(EPOCH FROM (COALESCE(cwq.started_at, NOW()) - cwq.created_at))::INT AS wait_seconds,
    EXTRACT(EPOCH FROM (COALESCE(cwq.completed_at, NOW()) - cwq.started_at))::INT AS run_seconds,
    tn.node_name     AS assigned_node_name,
    tn.hostname      AS assigned_node_host,
    tt.node_name     AS target_node_name,
    CASE
        WHEN cwq.status = 'completed' THEN 'ok'
        WHEN cwq.status = 'failed'    THEN COALESCE(cwq.result->>'error', 'error')
        ELSE NULL
    END AS outcome_summary
FROM cluster_work_queue cwq
LEFT JOIN remote_nodes tn ON tn.id = cwq.assigned_node_id
LEFT JOIN remote_nodes tt ON tt.id = cwq.target_node_id
WHERE cwq.created_at > NOW() - INTERVAL '24 hours';

CREATE OR REPLACE VIEW v_cluster_queue_summary AS
SELECT
    status,
    work_type,
    COUNT(*)                                    AS count,
    AVG(EXTRACT(EPOCH FROM (NOW() - created_at)))::INT AS avg_age_seconds,
    rn.node_name                                AS node_name
FROM cluster_work_queue cwq
LEFT JOIN remote_nodes rn ON rn.id = cwq.assigned_node_id
WHERE cwq.created_at > NOW() - INTERVAL '1 hour'
GROUP BY status, work_type, rn.node_name;
```

---

## New Files to Create

### `platform_v2/services/cluster_queue_router.py`

```python
"""
ClusterQueueRouter — unified work queue router for cluster_work_queue.
Polled every 15s via Job #130 in department_hq/jobs.py.
"""
import logging
from typing import Optional
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Capability → preferred node tier
# Hub-only: capabilities that require core platform DB access or large context
HUB_ONLY_CAPABILITIES = frozenset({
    "conversation", "dispatch", "embedding", "knowledge_analysis",
    "compliance", "security",
})

CAPABILITY_NODE_PREFERENCE = {
    # Hub-only
    "conversation": "hub",
    "dispatch": "hub",
    "embedding": "hub",
    "knowledge_analysis": "hub",
    "compliance": "hub",
    "security": "hub",
    # Starship-preferred (GPU, medium models)
    "code": "starship",
    "code_review": "starship",
    "debug": "starship",
    "research": "starship",
    "analyze": "starship",
    "image_generation": "starship",
    "vision": "starship",
    "summarize": "starship",
    # Outpost-preferred (CPU small models, co-located with WTF/Watch products)
    "classify": "outpost",
    "bias_analysis": "outpost",
    "fact_check": "outpost",
    "geo_extraction": "outpost",
    "translate": "outpost",
    "_default": "hub",
}

_NODE_ID_CACHE: dict = {}  # tier_label → [remote_nodes.id, ...]


class ClusterQueueRouter:
    """Singleton router. Call get_cluster_router() to obtain instance."""

    def __init__(self):
        self._node_capacity_cache: dict = {}  # node_id → {vram_free_gb, ram_free_gb, active_jobs}

    def enqueue(
        self,
        work_type: str,
        capability: str,
        payload: dict,
        *,
        priority: int = 5,
        requester: str = "agent_loop",
        agent_name: str = None,
        agent_id: int = None,
        module_id: str = None,
        source_product: str = None,
        user_id: int = None,
        target_node_id: int = None,
        callback_type: str = None,
        callback_data: dict = None,
        legacy_dpq_id: int = None,
        legacy_bridge_job_id: int = None,
    ) -> int:
        """Insert a row into cluster_work_queue. Returns the new id."""
        import psycopg2
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO cluster_work_queue
                   (work_type, capability, payload, priority, requester,
                    agent_name, agent_id, module_id, source_product, user_id,
                    target_node_id, callback_type, callback_data,
                    legacy_dpq_id, legacy_bridge_job_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (work_type, capability, psycopg2.extras.Json(payload), priority, requester,
                 agent_name, agent_id, module_id, source_product, user_id,
                 target_node_id, callback_type,
                 psycopg2.extras.Json(callback_data) if callback_data else None,
                 legacy_dpq_id, legacy_bridge_job_id),
            )
            return cur.fetchone()["id"]

    def poll_and_route(self) -> int:
        """Main poll loop — called by Job #130 every 15s.

        1. Refresh node capacity cache.
        2. Claim pending rows (SELECT FOR UPDATE SKIP LOCKED, LIMIT 20).
        3. For each row: resolve target node, set status='assigned'.
        4. Also reap stuck 'running' rows older than 30min.
        Returns count of rows routed.
        """
        self._refresh_node_capacity()
        routed = self._route_pending()
        self._reap_zombies()
        return routed

    def _route_pending(self) -> int:
        count = 0
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """SELECT id, capability, work_type, payload, target_node_id
                   FROM cluster_work_queue
                   WHERE status = 'pending'
                   ORDER BY priority DESC, created_at ASC
                   LIMIT 20
                   FOR UPDATE SKIP LOCKED"""
            )
            rows = cur.fetchall()
            for row in rows:
                node_id = row["target_node_id"] or self._select_node(
                    row["capability"], row["work_type"], row["payload"]
                )
                cur.execute(
                    """UPDATE cluster_work_queue
                       SET status='assigned', assigned_node_id=%s
                       WHERE id=%s""",
                    (node_id, row["id"]),
                )
                count += 1
        return count

    def _reap_zombies(self) -> None:
        """Reset stuck 'running' rows older than 30 minutes."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE cluster_work_queue
                   SET status='failed',
                       result='{"error": "zombie_reaped"}'::jsonb,
                       completed_at=NOW()
                   WHERE status='running'
                     AND started_at < NOW() - INTERVAL '30 minutes'"""
            )

    def mark_running(self, queue_id: int) -> None:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE cluster_work_queue SET status='running', started_at=NOW() WHERE id=%s",
                (queue_id,),
            )

    def complete(self, queue_id: int, result: dict) -> None:
        import psycopg2
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE cluster_work_queue
                   SET status='completed', result=%s, completed_at=NOW() WHERE id=%s""",
                (psycopg2.extras.Json(result), queue_id),
            )

    def fail(self, queue_id: int, error: str, *, retry: bool = True) -> None:
        import psycopg2
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT retry_count, max_retries FROM cluster_work_queue WHERE id=%s", (queue_id,))
            row = cur.fetchone()
            if retry and row and row["retry_count"] < row["max_retries"]:
                cur.execute(
                    """UPDATE cluster_work_queue
                       SET status='pending', retry_count=retry_count+1 WHERE id=%s""",
                    (queue_id,),
                )
            else:
                cur.execute(
                    """UPDATE cluster_work_queue
                       SET status='failed', result=%s, completed_at=NOW() WHERE id=%s""",
                    (psycopg2.extras.Json({"error": error}), queue_id),
                )

    def _refresh_node_capacity(self) -> None:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, heartbeat_data
                   FROM remote_nodes WHERE status='online'"""
            )
            rows = cur.fetchall()
            cur.execute(
                """SELECT assigned_node_id, COUNT(*) AS active_jobs
                   FROM cluster_work_queue
                   WHERE status IN ('assigned','running')
                     AND assigned_node_id IS NOT NULL
                   GROUP BY assigned_node_id"""
            )
            job_counts = {r["assigned_node_id"]: r["active_jobs"] for r in cur.fetchall()}
        for row in rows:
            hb = row["heartbeat_data"] or {}
            self._node_capacity_cache[row["id"]] = {
                "vram_free_gb": hb.get("gpu_vram_gb", 0),
                "ram_free_gb": hb.get("ram_gb", 0),
                "active_jobs": job_counts.get(row["id"], 0),
            }

    def _select_node(self, capability: str, work_type: str, payload: dict) -> Optional[int]:
        """Return best remote_nodes.id. Fallback: None (hub handles it)."""
        if capability in HUB_ONLY_CAPABILITIES:
            return None  # Hub only — dispatcher handles
        tier = CAPABILITY_NODE_PREFERENCE.get(capability, CAPABILITY_NODE_PREFERENCE["_default"])
        # For now, return None (hub) until node tier labels are populated in remote_nodes
        # TODO: map tier label → remote_nodes.id set via deployment_mode/node_name
        return None


_router_instance: Optional[ClusterQueueRouter] = None


def get_cluster_router() -> ClusterQueueRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = ClusterQueueRouter()
    return _router_instance
```

### `platform_v2/services/cluster_queue_adapter.py`

```python
"""
ClusterQueueAdapter — dual-write shim for transition period.
Called at existing dispatch_pending_queue INSERT sites.
Writes to cluster_work_queue in addition to the legacy table.
Remove this adapter once transition is complete (target: 30 days post-migration).
"""
from .cluster_queue_router import get_cluster_router
import logging
logger = logging.getLogger(__name__)


def mirror_dpq_insert(
    capability: str,
    model_needed: str,
    prompt: str,
    system_prompt: str,
    json_mode: bool,
    agent_name: str,
    agent_id: int,
    module_id: str,
    source_product: str,
    requested_by: str,
    user_id: int,
    priority: int,
    preferred_node_id=None,
    callback_type: str = None,
    callback_data: dict = None,
    legacy_dpq_id: int = None,
) -> None:
    """Mirror a dispatch_pending_queue insert into cluster_work_queue.
    Swallows all exceptions — must never break the caller's insert path.
    Note: preferred_node_id in dispatch_pending_queue is a string alias, not FK int.
    Resolve it via _resolve_node_id() before passing.
    """
    try:
        node_id = _resolve_node_id(preferred_node_id) if preferred_node_id else None
        get_cluster_router().enqueue(
            work_type="inference",
            capability=capability,
            payload={
                "model": model_needed,
                "prompt": prompt,
                "system_prompt": system_prompt,
                "json_mode": json_mode,
            },
            priority=priority,
            requester="agent_loop",
            agent_name=agent_name,
            agent_id=agent_id,
            module_id=module_id,
            source_product=source_product,
            user_id=user_id,
            target_node_id=node_id,
            callback_type=callback_type,
            callback_data=callback_data,
            legacy_dpq_id=legacy_dpq_id,
        )
    except Exception as exc:
        logger.warning("cluster_queue_adapter mirror failed: %s", exc)


def _resolve_node_id(alias: str) -> Optional[int]:
    """Resolve string node alias → remote_nodes.id. Returns None if not found."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM remote_nodes WHERE node_name=%s OR hostname=%s OR mesh_ip=%s LIMIT 1",
                (alias, alias, alias),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception:
        return None
```

---

## Job #130 Registration

Add to `platform_v2/tools/department_hq/jobs.py`:

```python
# Job #130 — Cluster Queue Router (every 15s)
def _run_cluster_queue_router():
    try:
        from services.cluster_queue_router import get_cluster_router
        routed = get_cluster_router().poll_and_route()
        if routed:
            logger.info("[ClusterQueue] Routed %d work items", routed)
    except Exception as e:
        logger.error("[ClusterQueue] Router cycle failed: %s", e)

scheduler.add_job(
    _run_cluster_queue_router,
    "interval",
    seconds=15,
    id="cluster_queue_router",
    max_instances=1,
    coalesce=True,
    timezone="America/Toronto",
)
```

---

## Node Capacity Routing Table

| Capability | Preferred Tier | Rationale |
|---|---|---|
| `conversation`, `dispatch`, `embedding`, `knowledge_analysis`, `compliance`, `security` | Hub | Core platform DB access, Quadro M4000, 128GB RAM |
| `code`, `code_review`, `debug`, `research`, `analyze`, `image_generation`, `vision`, `summarize` | Starship | GPU-accelerated, RTX 3070, 7B–13B class |
| `classify`, `bias_analysis`, `fact_check`, `geo_extraction`, `translate` | Outpost | CPU, 1.5B–3B, co-located with WTF/Watch on VPS |
| All others | Hub (fallback) | Hub always has CPU RAM headroom |

VRAM budget rules:
- Hub Quadro M4000 (8GB): max 3.9GB GPU models warm simultaneously, remainder CPU
- Starship-246 (RTX 3070 8GB): max 3 loaded models, GPU up to ~6GB
- Starship-245 (RTX 3050 4GB): max 2 loaded models, GPU up to ~3.5GB
- Outpost: CPU only, 8GB RAM, models 1.5B–3B only

---

## Migration Plan

**Phase 1 — Add table, wire adapter (Day 0)**
1. Run `395_cluster_work_queue.sql`
2. Deploy `cluster_queue_router.py` + `cluster_queue_adapter.py`
3. Register Job #130 (15s poll)
4. At both `INSERT INTO dispatch_pending_queue` sites in `department_dispatcher.py` (lines ~5664, ~5792): call `mirror_dpq_insert()` after the existing INSERT, passing the returned `legacy_dpq_id`
5. At `INSERT INTO dispatch_pending_queue` in `proposal_service.py` (line ~1429): same pattern
6. Run `396_v_cluster_queue_status.sql`
7. Wire `v_cluster_queue_status` into Fleet tab Dispatch panel endpoint (`GET /api/fleet/queue-status`)

**Phase 2 — Validate (Days 1–30)**
- Monitor `cluster_work_queue` row counts track `dispatch_pending_queue` within 5%
- Verify router routes items without interfering with `model_dispatch_worker`
- Fleet tab Dispatch panel shows unified view

**Phase 3 — Cut over bridge_jobs (Day 14)**
- Mirror `bridge_jobs` inserts with `work_type='maintenance'`, `legacy_bridge_job_id` set

**Phase 4 — Transition complete (Day 30)**
- Remove `cluster_queue_adapter.py` and all call sites
- `dispatch_pending_queue` → append-only archive
- `cluster_work_queue` is sole source of truth

**NOTE:** `media_generation_queue` stays separate — own 30s worker + ComfyUI-specific poll/fetch loop. Cluster queue tracks `generation` work as proxy only.

---

## Open Questions

1. **Hub-only enforcement**: `embedding`, `knowledge_analysis`, `compliance` require direct PostgreSQL access inside Docker network. Implement as `HUB_ONLY_CAPABILITIES` frozenset (already in service skeleton above).

2. **`preferred_node_id` type mismatch**: In `dispatch_pending_queue` it is a string alias, not FK int. The adapter `_resolve_node_id()` handles this.

3. **`model_dispatch_worker` still drains `dispatch_pending_queue`**: During Phase 1–2, both the existing worker AND the new router poll for work. The router only sets `cluster_work_queue.status='assigned'` — it does NOT execute inference. Actual execution still happens via existing `model_dispatch_worker`. The router is a **metadata layer only** until Phase 3+.

4. **`bridge_jobs.status='pending_approval'`**: The approval surface (`GET /api/approvals/pending`) returns `bridge:` prefixed IDs. After Phase 3, the approval surface must also read `cluster_work_queue WHERE payload->>'requires_approval'='true'`. Plan migration of `approvals_routes.py` at Phase 3.

5. **Zombie reaper compatibility**: Job #120 reaps `dispatch_pending_queue`. The new `_reap_zombies()` in `poll_and_route()` handles `cluster_work_queue` stuck-running rows — no new job needed.

---

## Build Sequence

- [ ] **Step 1**: Run `395_cluster_work_queue.sql` + `396_v_cluster_queue_status.sql`
- [ ] **Step 2**: Create `cluster_queue_router.py` + `cluster_queue_adapter.py` in `platform_v2/services/`
- [ ] **Step 3**: Register Job #130 in `department_hq/jobs.py`
- [ ] **Step 4**: Wire `mirror_dpq_insert()` at the 3 `dispatch_pending_queue` INSERT sites
- [ ] **Step 5**: Wire `v_cluster_queue_status` into Fleet tab Dispatch panel endpoint
- [ ] **Step 6**: Deploy + monitor for 30 days
- [ ] **Step 7 (Day 14)**: Mirror `bridge_jobs` inserts
- [ ] **Step 8 (Day 30)**: Remove adapter, archive legacy tables
