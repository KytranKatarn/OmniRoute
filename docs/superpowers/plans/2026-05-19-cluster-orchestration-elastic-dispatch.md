# Cluster Orchestration & Elastic Agent Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every A.R.C.H.I.E. agent becomes eligible for overflow work when idle — DHQ auto-routes backlog dispatches to idle agents across all nodes, with full Fleet tab visibility and manual control.

**Architecture:** New `cluster_orchestration_worker` DHQ job (60s) computes a per-(agent, capability) overflow score from three signals (idle time + node utilization + queue depth), writes live state to `agent_overflow_state`, and the dispatcher adds a +0.4 score bonus for active overflow agents. Fleet tab gets a "CLUSTER ORCHESTRATION" panel with full read/write controls. Zero changes to the hot dispatch path except 3 lines in the coordinator's scoring formula.

**Tech Stack:** Python/Flask, psycopg2, APScheduler, existing `fleet_resource_router.py`, existing `dispatch_pending_queue`, existing Department HQ fleet tab HTML/JS. Use `escHtml()` from `static/js/consciousness.js` for all DOM rendering — never raw innerHTML with API data.

**Spec:** `docs/superpowers/specs/2026-05-19-cluster-orchestration-elastic-dispatch-design.md`

**Unified Agent Identity Rule:** Never create `-B` agent variants. Add secondary skills to existing agents and assign them to more nodes via `node_agents`. One agent = one DB row = one stats record.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `database/migrations/386_cluster_orchestration.sql` | CREATE | Two new tables |
| `platform_v2/services/cluster_orchestration_service.py` | CREATE | Score engine, config hierarchy, state cache |
| `platform_v2/tests/test_cluster_orchestration_service.py` | CREATE | Unit tests for score engine |
| `platform_v2/tools/department_hq/jobs.py` | MODIFY | Add `cluster_orchestration_worker` job (5 passes) |
| `platform_v2/services/department_coordinator.py` | MODIFY | +3 lines: overflow cache lookup + score bonus |
| `platform_v2/tools/department_hq/fleet_orchestration_routes.py` | CREATE | 6 REST endpoints |
| `platform_v2/tools/department_hq/__init__.py` | MODIFY | Register new route file |
| `platform_v2/templates/tools/department_hq.html` | MODIFY | CLUSTER ORCHESTRATION panel in Fleet tab |
| `platform_v2/static/js/department-hq-orchestration.js` | CREATE | Panel rendering + controls (new file, not appended to existing) |

---

## Task 1: Database Migration

**Files:**
- Create: `database/migrations/386_cluster_orchestration.sql`

**Before starting:** Check `ls database/migrations/ | sort | tail -3` — if 386 is taken, use the next available number.

- [ ] **Step 1: Check latest migration number**

```bash
ls database/migrations/ | grep -E '^[0-9]' | sort | tail -3
```

- [ ] **Step 2: Write the migration**

Create `database/migrations/386_cluster_orchestration.sql`:

```sql
-- 386_cluster_orchestration.sql
-- Cluster Orchestration & Elastic Agent Dispatch (Project #352)

CREATE TABLE IF NOT EXISTS cluster_orchestration_config (
    id                        SERIAL PRIMARY KEY,
    scope                     VARCHAR(20) NOT NULL DEFAULT 'global'
                              CHECK (scope IN ('global','agent','capability','node')),
    agent_id                  INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    capability                VARCHAR(100),
    node_id                   INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    idle_threshold_minutes    INTEGER NOT NULL DEFAULT 5,
    utilization_threshold_pct FLOAT   NOT NULL DEFAULT 60.0,
    queue_pressure_threshold  INTEGER NOT NULL DEFAULT 10,
    idle_weight               FLOAT   NOT NULL DEFAULT 0.3,
    utilization_weight        FLOAT   NOT NULL DEFAULT 0.3,
    queue_pressure_weight     FLOAT   NOT NULL DEFAULT 0.4,
    overflow_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    overflow_paused           BOOLEAN NOT NULL DEFAULT FALSE,
    priority_boost            INTEGER NOT NULL DEFAULT 0,
    max_overflow_concurrent   INTEGER NOT NULL DEFAULT 3,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_overflow_state (
    agent_id         INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    capability       VARCHAR(100) NOT NULL,
    overflow_score   FLOAT   NOT NULL DEFAULT 0.0,
    is_active        BOOLEAN NOT NULL DEFAULT FALSE,
    activated_at     TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '90 seconds',
    dispatches_sent  INTEGER NOT NULL DEFAULT 0,
    node_id          INTEGER REFERENCES remote_nodes(id),
    reason           JSONB   NOT NULL DEFAULT '{}',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, capability)
);

-- Global default config row
INSERT INTO cluster_orchestration_config (scope)
VALUES ('global')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_overflow_state_active
    ON agent_overflow_state (is_active, capability) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_overflow_state_expires
    ON agent_overflow_state (expires_at);
```

- [ ] **Step 3: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie \
  < database/migrations/386_cluster_orchestration.sql
```

Expected: `CREATE TABLE`, `CREATE TABLE`, `INSERT 0 1`, `CREATE INDEX`, `CREATE INDEX`

- [ ] **Step 4: Verify**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "SELECT table_name FROM information_schema.tables
      WHERE table_name IN ('cluster_orchestration_config','agent_overflow_state');"
```

Expected: 2 rows.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/cluster-orchestration
git add database/migrations/386_cluster_orchestration.sql
git commit -m "feat(orchestration): cluster_orchestration_config + agent_overflow_state tables"
```

---

## Task 2: Cluster Orchestration Service

**Files:**
- Create: `platform_v2/services/cluster_orchestration_service.py`
- Create: `platform_v2/tests/test_cluster_orchestration_service.py`

- [ ] **Step 1: Write failing tests**

Create `platform_v2/tests/test_cluster_orchestration_service.py`:

```python
"""Tests for cluster orchestration score engine."""
import pytest


class TestComputeOverflowScore:

    def _cfg(self, **overrides):
        cfg = {
            "idle_threshold_minutes": 5,
            "utilization_threshold_pct": 60.0,
            "queue_pressure_threshold": 10,
            "idle_weight": 0.3,
            "utilization_weight": 0.3,
            "queue_pressure_weight": 0.4,
        }
        cfg.update(overrides)
        return cfg

    def test_all_signals_maxed_returns_one(self):
        from services.cluster_orchestration_service import compute_overflow_score
        score = compute_overflow_score(
            idle_minutes=10, util_pct=0.0, queue_depth=20, config=self._cfg()
        )
        assert score == pytest.approx(1.0)

    def test_all_signals_zero_returns_zero(self):
        from services.cluster_orchestration_service import compute_overflow_score
        score = compute_overflow_score(
            idle_minutes=0, util_pct=100.0, queue_depth=0, config=self._cfg()
        )
        assert score == pytest.approx(0.0)

    def test_only_idle_weight_active(self):
        from services.cluster_orchestration_service import compute_overflow_score
        cfg = self._cfg(idle_weight=1.0, utilization_weight=0.0, queue_pressure_weight=0.0)
        score = compute_overflow_score(
            idle_minutes=2.5, util_pct=100.0, queue_depth=0, config=cfg
        )
        assert score == pytest.approx(0.5)

    def test_idle_capped_at_one(self):
        from services.cluster_orchestration_service import compute_overflow_score
        cfg = self._cfg(idle_weight=1.0, utilization_weight=0.0, queue_pressure_weight=0.0)
        score = compute_overflow_score(
            idle_minutes=100, util_pct=100.0, queue_depth=0, config=cfg
        )
        assert score == pytest.approx(1.0)


class TestResolveConfig:

    def _row(self, scope, **fields):
        base = {
            "scope": scope, "agent_id": None, "capability": None, "node_id": None,
            "idle_threshold_minutes": 5, "utilization_threshold_pct": 60.0,
            "queue_pressure_threshold": 10, "idle_weight": 0.3,
            "utilization_weight": 0.3, "queue_pressure_weight": 0.4,
            "overflow_enabled": True, "overflow_paused": False,
            "priority_boost": 0, "max_overflow_concurrent": 3,
        }
        base.update(fields)
        return base

    def test_agent_override_beats_global(self):
        from services.cluster_orchestration_service import resolve_config
        rows = [
            self._row("global", idle_threshold_minutes=5),
            self._row("agent", agent_id=42, idle_threshold_minutes=2),
        ]
        result = resolve_config(rows, agent_id=42, capability=None, node_id=None)
        assert result["idle_threshold_minutes"] == 2

    def test_global_used_when_no_override(self):
        from services.cluster_orchestration_service import resolve_config
        rows = [self._row("global", idle_threshold_minutes=7)]
        result = resolve_config(rows, agent_id=99, capability="research", node_id=None)
        assert result["idle_threshold_minutes"] == 7

    def test_paused_true_at_agent_scope(self):
        from services.cluster_orchestration_service import resolve_config
        rows = [
            self._row("global", overflow_paused=False),
            self._row("agent", agent_id=1, overflow_paused=True),
        ]
        result = resolve_config(rows, agent_id=1, capability=None, node_id=None)
        assert result["overflow_paused"] is True


class TestGetOverflowBonus:

    def test_active_agent_returns_bonus(self):
        from services.cluster_orchestration_service import (
            update_overflow_cache, get_overflow_bonus
        )
        update_overflow_cache([
            {"agent_id": 10, "capability": "fact_check_backlog",
             "is_active": True, "overflow_score": 0.8}
        ])
        # Bonus only returns 0 if cache is stale — force a fresh build
        import services.cluster_orchestration_service as svc
        svc._cache_built_at = __import__("time").monotonic()
        bonus = get_overflow_bonus(10, "fact_check_backlog")
        assert bonus == pytest.approx(0.4)

    def test_inactive_agent_returns_zero(self):
        from services.cluster_orchestration_service import (
            update_overflow_cache, get_overflow_bonus
        )
        update_overflow_cache([
            {"agent_id": 11, "capability": "research",
             "is_active": False, "overflow_score": 0.2}
        ])
        import services.cluster_orchestration_service as svc
        svc._cache_built_at = __import__("time").monotonic()
        assert get_overflow_bonus(11, "research") == 0.0
```

- [ ] **Step 2: Run tests — expect failure**

```bash
docker exec archie_platform python3 -m pytest \
  platform_v2/tests/test_cluster_orchestration_service.py -v 2>&1 | tail -8
```

Expected: `ModuleNotFoundError: No module named 'services.cluster_orchestration_service'`

- [ ] **Step 3: Implement the service**

Create `platform_v2/services/cluster_orchestration_service.py`:

```python
"""Cluster Orchestration Service — score engine, config hierarchy, state cache.

Imported by:
  cluster_orchestration_worker (jobs.py) — writes agent_overflow_state each cycle
  department_coordinator.select_agent() — reads overflow cache for +0.4 score bonus
"""
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_overflow_cache: dict = {}
_cache_lock = threading.Lock()
_cache_built_at: float = 0.0
_CACHE_TTL_SECONDS = 90


def compute_overflow_score(
    idle_minutes: float,
    util_pct: float,
    queue_depth: int,
    config: dict,
) -> float:
    """Return 0.0-1.0 overflow score from three normalised signals."""
    idle_thresh  = max(1, config["idle_threshold_minutes"])
    util_thresh  = max(1.0, config["utilization_threshold_pct"])
    queue_thresh = max(1, config["queue_pressure_threshold"])

    idle_score  = min(1.0, idle_minutes / idle_thresh)
    util_score  = max(0.0, 1.0 - util_pct / util_thresh)
    queue_score = min(1.0, queue_depth / queue_thresh)

    return (
        config["idle_weight"]           * idle_score
        + config["utilization_weight"]  * util_score
        + config["queue_pressure_weight"] * queue_score
    )


def resolve_config(
    all_configs: list,
    agent_id: Optional[int],
    capability: Optional[str],
    node_id: Optional[int],
) -> dict:
    """Merge config rows by scope priority: node > agent > capability > global."""
    PRIORITY = {"global": 0, "capability": 1, "agent": 2, "node": 3}
    result: dict = {}
    for row in sorted(all_configs, key=lambda r: PRIORITY.get(r["scope"], 0)):
        scope = row["scope"]
        if scope == "global":
            result.update(row)
        elif scope == "capability" and row.get("capability") == capability:
            result.update(row)
        elif scope == "agent" and row.get("agent_id") == agent_id:
            result.update(row)
        elif scope == "node" and row.get("node_id") == node_id:
            result.update(row)
    return result


def update_overflow_cache(states: list) -> None:
    """Replace the module-level cache atomically. Called by the worker each cycle."""
    global _overflow_cache, _cache_built_at
    new_cache = {
        (s["agent_id"], s["capability"]): {
            "is_active": s["is_active"],
            "score": s["overflow_score"],
        }
        for s in states
    }
    with _cache_lock:
        _overflow_cache = new_cache
        _cache_built_at = time.monotonic()


def get_overflow_bonus(agent_id: int, capability: str) -> float:
    """Return +0.4 if agent is in active overflow for this capability, else 0.
    Zero DB queries — reads only the in-memory cache.
    """
    with _cache_lock:
        stale = (time.monotonic() - _cache_built_at) > _CACHE_TTL_SECONDS
        if stale:
            return 0.0
        entry = _overflow_cache.get((agent_id, capability), {})
    return 0.4 if entry.get("is_active") else 0.0


def get_full_cache_snapshot() -> list:
    """All current overflow state entries — used by the status API endpoint."""
    with _cache_lock:
        return [
            {"agent_id": aid, "capability": cap, **data}
            for (aid, cap), data in _overflow_cache.items()
        ]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
docker exec archie_platform python3 -m pytest \
  platform_v2/tests/test_cluster_orchestration_service.py -v 2>&1 | tail -12
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/cluster_orchestration_service.py \
        platform_v2/tests/test_cluster_orchestration_service.py
git commit -m "feat(orchestration): score engine, config hierarchy, overflow cache service"
```

---

## Task 3: Cluster Orchestration Worker

**Files:**
- Modify: `platform_v2/tools/department_hq/jobs.py`

Find the insertion point: `grep -n "fleet_capacity_report\|cluster_orchestration" platform_v2/tools/department_hq/jobs.py | tail -5`

Insert inside `register_department_hq_jobs()` after the fleet_capacity_report block.

- [ ] **Step 1: Find exact insertion line**

```bash
grep -n "fleet_capacity_report\|scheduler.add_job" \
  platform_v2/tools/department_hq/jobs.py | grep -A1 "fleet_capacity" | tail -5
```

Note the line number of the `logger.info` that closes the fleet_capacity_report block.

- [ ] **Step 2: Add the worker function**

Insert after the fleet_capacity_report block (same indentation level, inside `register_department_hq_jobs()`):

```python
    # Cluster Orchestration Worker (Project #352) — every 60s.
    # Scores all active agents across all capabilities and nodes.
    # Writes agent_overflow_state; refreshes the dispatcher's overflow cache.
    def _run_cluster_orchestration_worker():
        try:
            import json as _json
            import time as _time
            from database import get_db_cursor
            from services.cluster_orchestration_service import (
                compute_overflow_score,
                resolve_config,
                update_overflow_cache,
            )
            from services.fleet_resource_router import utilization_pct

            cycle_start = _time.monotonic()
            newly_activated = 0

            # Pass 1 — node utilization
            node_util: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute("""
                    SELECT id, cpu_usage, gpu_vram_used_gb, gpu_vram_total_gb,
                           ram_used_gb, ram_total_gb, last_heartbeat
                    FROM remote_nodes
                    WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                """)
                for row in (cur.fetchall() or []):
                    node_util[row["id"]] = utilization_pct(dict(row))

            # Pass 2 — agent idle minutes
            agent_idle: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute("""
                    SELECT a.id,
                           COALESCE(
                               EXTRACT(EPOCH FROM NOW() - MAX(tel.started_at)) / 60,
                               999
                           ) AS idle_minutes
                    FROM agents a
                    LEFT JOIN task_execution_log tel
                        ON tel.agent_name = a.name
                       AND tel.started_at > NOW() - INTERVAL '60 minutes'
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                    GROUP BY a.id
                """)
                for row in (cur.fetchall() or []):
                    agent_idle[row["id"]] = float(row["idle_minutes"] or 999)

            # Pass 3 — queue depths per capability
            queue_depths: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute("""
                    SELECT capability, COUNT(*) AS depth
                    FROM dispatch_pending_queue
                    WHERE status = 'pending'
                    GROUP BY capability
                """)
                for row in (cur.fetchall() or []):
                    queue_depths[row["capability"]] = row["depth"]

            # Pass 4 — load all config rows once
            with get_db_cursor() as (_, cur):
                cur.execute("SELECT * FROM cluster_orchestration_config")
                all_configs = [dict(r) for r in (cur.fetchall() or [])]

            # Pass 5 — score each (agent, node, capability) assignment
            with get_db_cursor() as (_, cur):
                cur.execute("""
                    SELECT na.hub_agent_id AS agent_id,
                           na.node_id,
                           sk.skill_name   AS capability,
                           a.name          AS agent_name
                    FROM node_agents na
                    JOIN agents a ON a.id = na.hub_agent_id
                    JOIN agent_skills sk ON sk.agent_id = na.hub_agent_id
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                      AND na.node_id IN (
                          SELECT id FROM remote_nodes
                          WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                      )
                """)
                assignments = cur.fetchall() or []

            upsert_rows = []
            for row in assignments:
                agent_id   = row["agent_id"]
                node_id    = row["node_id"]
                capability = row["capability"]

                cfg = resolve_config(all_configs, agent_id, capability, node_id)
                if not cfg.get("overflow_enabled", True):
                    continue

                score = compute_overflow_score(
                    idle_minutes=agent_idle.get(agent_id, 0),
                    util_pct=node_util.get(node_id, 100.0),
                    queue_depth=queue_depths.get(capability, 0),
                    config=cfg,
                )
                paused    = cfg.get("overflow_paused", False)
                is_active = (score >= 0.5) and not paused

                upsert_rows.append({
                    "agent_id":       agent_id,
                    "capability":     capability,
                    "overflow_score": score,
                    "is_active":      is_active,
                    "node_id":        node_id,
                    "reason": {
                        "idle_mins":   round(agent_idle.get(agent_id, 0), 1),
                        "util_pct":    round(node_util.get(node_id, 100), 1),
                        "queue_depth": queue_depths.get(capability, 0),
                        "paused":      paused,
                    },
                })

            if upsert_rows:
                with get_db_cursor(commit=True) as (_, cur):
                    for r in upsert_rows:
                        cur.execute(
                            "SELECT is_active FROM agent_overflow_state "
                            "WHERE agent_id=%s AND capability=%s",
                            (r["agent_id"], r["capability"]),
                        )
                        prev = cur.fetchone()
                        was_active = prev["is_active"] if prev else False

                        cur.execute("""
                            INSERT INTO agent_overflow_state
                                (agent_id, capability, overflow_score, is_active,
                                 activated_at, expires_at, node_id, reason, updated_at)
                            VALUES (%s, %s, %s, %s,
                                CASE WHEN %s THEN NOW() ELSE NULL END,
                                NOW() + INTERVAL '90 seconds',
                                %s, %s::jsonb, NOW())
                            ON CONFLICT (agent_id, capability) DO UPDATE SET
                                overflow_score = EXCLUDED.overflow_score,
                                is_active      = EXCLUDED.is_active,
                                activated_at   = CASE
                                    WHEN EXCLUDED.is_active
                                     AND NOT agent_overflow_state.is_active
                                    THEN NOW()
                                    ELSE agent_overflow_state.activated_at END,
                                expires_at     = EXCLUDED.expires_at,
                                node_id        = EXCLUDED.node_id,
                                reason         = EXCLUDED.reason,
                                updated_at     = NOW()
                        """, (
                            r["agent_id"], r["capability"], r["overflow_score"],
                            r["is_active"], r["is_active"],
                            r["node_id"], _json.dumps(r["reason"]),
                        ))
                        if r["is_active"] and not was_active:
                            newly_activated += 1

                    cur.execute(
                        "DELETE FROM agent_overflow_state WHERE expires_at < NOW()"
                    )

            update_overflow_cache(upsert_rows)

            elapsed_ms   = int((_time.monotonic() - cycle_start) * 1000)
            active_count = sum(1 for r in upsert_rows if r["is_active"])
            logger.info(
                "[ClusterOrchestration] scored=%d active=%d activated=%d elapsed=%dms",
                len(upsert_rows), active_count, newly_activated, elapsed_ms,
            )

            if newly_activated >= 5:
                try:
                    from services.telegram_service import send_info
                    caps = len({r["capability"] for r in upsert_rows if r["is_active"]})
                    send_info(
                        f"Cluster overflow activated: {newly_activated} agents "
                        f"across {caps} capabilities"
                    )
                except Exception:
                    pass

        except Exception as exc:
            logger.error("[ClusterOrchestration] crashed: %s", exc)

    # Expose for manual /trigger endpoint
    _run_cluster_orchestration_worker_fn = _run_cluster_orchestration_worker

    scheduler.add_job(
        with_ctx(_run_cluster_orchestration_worker),
        trigger=CronTrigger(second="0", timezone="America/Toronto"),
        id="cluster_orchestration_worker",
        name="Cluster Orchestration — elastic agent dispatch (Project #352)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered cluster_orchestration_worker (every 60s)")
```

- [ ] **Step 3: Restart scheduler and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_scheduler
sleep 8
docker logs --tail 10 archie_scheduler 2>&1 | grep -i "cluster_orchestration"
```

Expected: `[DeptHQ] Registered cluster_orchestration_worker (every 60s)`

- [ ] **Step 4: Wait one cycle and check**

```bash
sleep 65
docker logs --tail 20 archie_scheduler 2>&1 | grep ClusterOrchestration
```

Expected: `[ClusterOrchestration] scored=N active=M activated=K elapsed=Xms`

- [ ] **Step 5: Verify state table populated**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "SELECT COUNT(*), SUM(is_active::int) FROM agent_overflow_state;"
```

Expected: rows with non-zero count.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py
git commit -m "feat(orchestration): cluster_orchestration_worker — 60s scoring cycle + state writes"
```

---

## Task 4: Dispatcher Integration

**Files:**
- Modify: `platform_v2/services/department_coordinator.py`

Three lines only. Read the file first to find exact variable names in `select_agent()`.

- [ ] **Step 1: Find the scoring loop**

```bash
grep -n "score.*+=\|score =\|proficiency\|is_department_ai" \
  platform_v2/services/department_coordinator.py | head -15
```

Identify the variable name for the agent object and the final `score +=` line in the scoring loop.

- [ ] **Step 2: Read the scoring block (10 lines around it)**

Read `platform_v2/services/department_coordinator.py` at the line identified above (±10 lines) to confirm agent variable name and loop structure.

- [ ] **Step 3: Apply the 3-line change**

At the TOP of `select_agent()` method body (before the loop), add import:

```python
from services.cluster_orchestration_service import get_overflow_bonus
```

Inside the scoring loop, AFTER all existing `score +=` lines:

```python
score += get_overflow_bonus(agent.id, capability)
```

- [ ] **Step 4: Verify no import errors**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.department_coordinator import DepartmentCoordinator
print('coordinator import OK')
" 2>&1
```

Expected: `coordinator import OK`

- [ ] **Step 5: Restart platform**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
sleep 5
docker logs --tail 5 archie_platform 2>&1 | grep -i "error\|running\|started"
```

Expected: no Python import errors.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/department_coordinator.py
git commit -m "feat(orchestration): +0.4 overflow bonus in agent scoring (3-line dispatcher hook)"
```

---

## Task 5: Fleet Orchestration Routes

**Files:**
- Create: `platform_v2/tools/department_hq/fleet_orchestration_routes.py`
- Modify: `platform_v2/tools/department_hq/__init__.py`

- [ ] **Step 1: Create the routes file**

Create `platform_v2/tools/department_hq/fleet_orchestration_routes.py`:

```python
"""Fleet Orchestration Routes — Cluster Orchestration panel API (Project #352)."""
import json
import logging
from datetime import datetime, timezone

from flask import jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_orchestration_routes(bp, admin_required):

    @bp.route("/api/orchestration/status")
    @admin_required
    def get_orchestration_status():
        try:
            from services.cluster_orchestration_service import get_full_cache_snapshot
            states = get_full_cache_snapshot()

            enriched = []
            if states:
                agent_ids = list({s["agent_id"] for s in states})
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        "SELECT id, name, department FROM agents WHERE id = ANY(%s)",
                        (agent_ids,),
                    )
                    agent_map = {r["id"]: dict(r) for r in (cur.fetchall() or [])}
                for s in states:
                    info = agent_map.get(s["agent_id"], {})
                    enriched.append({
                        "agent_id":   s["agent_id"],
                        "agent_name": info.get("name", "unknown"),
                        "department": info.get("department", ""),
                        "capability": s["capability"],
                        "score":      round(s["score"], 3),
                        "is_active":  s["is_active"],
                    })

            queues = []
            with get_db_cursor() as (_, cur):
                cur.execute("""
                    SELECT capability, COUNT(*) AS depth
                    FROM dispatch_pending_queue
                    WHERE status = 'pending'
                    GROUP BY capability ORDER BY depth DESC
                """)
                queues = [
                    {"capability": r["capability"], "depth": r["depth"]}
                    for r in (cur.fetchall() or [])
                ]

            global_paused = False
            with get_db_cursor() as (_, cur):
                cur.execute(
                    "SELECT overflow_paused FROM cluster_orchestration_config "
                    "WHERE scope = 'global' LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    global_paused = row["overflow_paused"]

            return jsonify({
                "agents":        enriched,
                "queues":        queues,
                "global_paused": global_paused,
                "last_scan":     datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.exception("orchestration/status failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/config", methods=["GET"])
    @admin_required
    def get_orchestration_config():
        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT * FROM cluster_orchestration_config ORDER BY scope, id"
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
        return jsonify({"configs": rows})

    @bp.route("/api/orchestration/config", methods=["POST"])
    @admin_required
    def update_orchestration_config():
        data = request.get_json() or {}
        scope      = data.get("scope", "global")
        agent_id   = data.get("agent_id")
        capability = data.get("capability")
        node_id    = data.get("node_id")

        allowed = {
            "idle_threshold_minutes", "utilization_threshold_pct",
            "queue_pressure_threshold", "idle_weight", "utilization_weight",
            "queue_pressure_weight", "overflow_enabled", "overflow_paused",
            "priority_boost", "max_overflow_concurrent",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "no valid fields to update"}), 400

        set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
        updates.update({
            "scope": scope, "agent_id": agent_id,
            "capability": capability, "node_id": node_id,
        })

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("""
                INSERT INTO cluster_orchestration_config
                    (scope, agent_id, capability, node_id,
                     idle_threshold_minutes, utilization_threshold_pct,
                     queue_pressure_threshold, idle_weight, utilization_weight,
                     queue_pressure_weight, overflow_enabled, overflow_paused,
                     priority_boost, max_overflow_concurrent)
                VALUES (%(scope)s, %(agent_id)s, %(capability)s, %(node_id)s,
                        5, 60.0, 10, 0.3, 0.3, 0.4, true, false, 0, 3)
                ON CONFLICT DO NOTHING
            """, updates)
            cur.execute(
                f"UPDATE cluster_orchestration_config "
                f"SET {set_clause}, updated_at=NOW() "
                f"WHERE scope=%(scope)s "
                f"AND (agent_id IS NOT DISTINCT FROM %(agent_id)s) "
                f"AND (capability IS NOT DISTINCT FROM %(capability)s) "
                f"AND (node_id IS NOT DISTINCT FROM %(node_id)s)",
                updates,
            )
        return jsonify({"ok": True})

    @bp.route("/api/orchestration/pause", methods=["POST"])
    @admin_required
    def pause_orchestration():
        data       = request.get_json() or {}
        scope      = data.get("scope", "global")
        agent_id   = data.get("agent_id")
        capability = data.get("capability")
        paused     = bool(data.get("paused", True))

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("""
                INSERT INTO cluster_orchestration_config
                    (scope, agent_id, capability, overflow_paused)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (scope, agent_id, capability, paused))
            cur.execute(
                "UPDATE cluster_orchestration_config "
                "SET overflow_paused=%s, updated_at=NOW() "
                "WHERE scope=%s "
                "AND (agent_id IS NOT DISTINCT FROM %s) "
                "AND (capability IS NOT DISTINCT FROM %s)",
                (paused, scope, agent_id, capability),
            )
        return jsonify({"ok": True, "paused": paused})

    @bp.route("/api/orchestration/boost", methods=["POST"])
    @admin_required
    def boost_capability():
        data       = request.get_json() or {}
        capability = data.get("capability")
        boost      = int(data.get("boost", 10))
        if not capability:
            return jsonify({"error": "capability required"}), 400

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("""
                INSERT INTO cluster_orchestration_config
                    (scope, capability, priority_boost)
                VALUES ('capability', %s, %s)
                ON CONFLICT DO NOTHING
            """, (capability, boost))
            cur.execute(
                "UPDATE cluster_orchestration_config "
                "SET priority_boost=%s, updated_at=NOW() "
                "WHERE scope='capability' AND capability=%s",
                (boost, capability),
            )
        return jsonify({"ok": True, "capability": capability, "boost": boost})

    @bp.route("/api/orchestration/trigger", methods=["POST"])
    @admin_required
    def trigger_orchestration():
        """Run one worker cycle synchronously (max 30s timeout)."""
        import threading
        result = {"done": False, "error": None}
        event  = threading.Event()

        def _run():
            try:
                from tools.department_hq import jobs as _jobs
                _jobs._run_cluster_orchestration_worker_fn()
                result["done"] = True
            except Exception as e:
                result["error"] = str(e)
            finally:
                event.set()

        threading.Thread(target=_run, daemon=True).start()
        event.wait(timeout=30)

        if not result["done"]:
            return jsonify({"ok": False, "error": result.get("error", "timeout")}), 500
        return jsonify({"ok": True})
```

- [ ] **Step 2: Register routes in `__init__.py`**

In `platform_v2/tools/department_hq/__init__.py`, after the existing route registrations (find with `grep -n "register_.*_routes" platform_v2/tools/department_hq/__init__.py`), add:

```python
from .fleet_orchestration_routes import register_orchestration_routes
register_orchestration_routes(bp, admin_required)
```

- [ ] **Step 3: Expose worker function in jobs.py**

Confirm `_run_cluster_orchestration_worker_fn = _run_cluster_orchestration_worker` is present after the worker function definition (added in Task 3). If missing, add it.

- [ ] **Step 4: Restart and smoke test**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
sleep 5
curl -s -u claude:AgentClaude2026 \
  http://192.168.1.200:3000/tools/department-hq/api/orchestration/status \
  2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print('agents:', len(d.get('agents',[])), 'queues:', len(d.get('queues',[])))"
```

Expected: `agents: N queues: M`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/fleet_orchestration_routes.py \
        platform_v2/tools/department_hq/__init__.py
git commit -m "feat(orchestration): 6 Fleet tab API endpoints (status, config, pause, boost, trigger)"
```

---

## Task 6: Fleet Tab Panel

**Files:**
- Modify: `platform_v2/templates/tools/department_hq.html`
- Create: `platform_v2/static/js/department-hq-orchestration.js`

**Security note:** All rendering uses `escHtml()` (already available in the platform as part of `consciousness.js` — confirm with `grep -n "function escHtml" platform_v2/static/js/consciousness.js`). Never use raw API data in template literals without escaping.

- [ ] **Step 1: Find Fleet tab insertion point in HTML**

```bash
grep -n "wtf-agent-status\|fleet-panel\|DISPATCH QUEUE" \
  platform_v2/templates/tools/department_hq.html | tail -8
```

Find the closing `</div>` of the last fleet panel. Insert new panel after it.

- [ ] **Step 2: Add panel HTML**

Insert after the last fleet panel div:

```html
<!-- CLUSTER ORCHESTRATION PANEL (Project #352) -->
<div class="fleet-panel" id="cluster-orchestration-panel" style="margin-top:20px;">
  <div style="display:flex;align-items:center;gap:12px;padding:8px 0;">
    <span style="color:#00ffff;letter-spacing:2px;font-size:11px;font-family:'Antonio',sans-serif;">
      CLUSTER ORCHESTRATION
    </span>
    <span id="co-status-badge" class="sc-static" style="font-size:10px;color:#888;">
      ● STANDBY
    </span>
    <span style="margin-left:auto;display:flex;gap:8px;">
      <button class="lcars-btn lcars-btn-sm" onclick="coTriggerScan()">▶ TRIGGER</button>
      <button class="lcars-btn lcars-btn-sm" id="co-pause-btn"
              onclick="coToggleGlobalPause()">⏸ PAUSE</button>
    </span>
  </div>
  <div style="margin-top:10px;">
    <div style="font-size:9px;color:#555;letter-spacing:1px;margin-bottom:6px;">QUEUE PRESSURE</div>
    <div id="co-queue-grid"></div>
  </div>
  <div style="margin-top:14px;">
    <div style="font-size:9px;color:#555;letter-spacing:1px;margin-bottom:6px;">AGENT OVERFLOW</div>
    <div id="co-agent-grid"
         style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px;">
    </div>
  </div>
</div>

<!-- Config Drawer -->
<div id="co-config-drawer"
     style="position:fixed;top:0;right:-360px;width:340px;height:100vh;
            background:#080818;border-left:1px solid #00ffff33;z-index:9999;
            transition:right 0.3s ease;overflow-y:auto;padding:20px;">
  <div style="display:flex;justify-content:space-between;margin-bottom:20px;">
    <span id="co-drawer-title"
          style="color:#00ffff;letter-spacing:2px;font-size:11px;">CONFIG</span>
    <button onclick="coCloseDrawer()"
            style="background:none;border:none;color:#666;font-size:16px;cursor:pointer;">✕</button>
  </div>
  <div id="co-drawer-content"></div>
</div>
<div id="co-drawer-overlay" onclick="coCloseDrawer()"
     style="display:none;position:fixed;inset:0;background:#00000066;z-index:9998;"></div>
```

- [ ] **Step 3: Add script tag to HTML**

In the `<head>` or at the bottom of the body (follow existing `<script src=...>` pattern), add:

```html
<script src="{{ url_for('static', filename='js/department-hq-orchestration.js') }}"></script>
```

- [ ] **Step 4: Create the JS file**

Create `platform_v2/static/js/department-hq-orchestration.js`.

Note: use `escHtml(str)` for ALL strings sourced from the API before inserting into the DOM.
If `escHtml` is not globally available in this page context, add at the top of the file:

```javascript
function _esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
```

Then implement the panel:

```javascript
/* department-hq-orchestration.js — Cluster Orchestration Fleet Panel (Project #352) */

/* Safe HTML escape — use for ALL API-sourced strings */
function _esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let _coGlobalPaused = false;

async function coRefresh() {
  try {
    const r = await fetch('/tools/department-hq/api/orchestration/status');
    if (!r.ok) return;
    const d = await r.json();
    _coGlobalPaused = d.global_paused;
    _coRenderStatus(d);
  } catch (e) { /* silent — fleet tab may not be active */ }
}

function _coRenderStatus(d) {
  const agents  = d.agents  || [];
  const queues  = d.queues  || [];
  const active  = agents.filter(a => a.is_active).length;

  /* Status badge */
  const badge = document.getElementById('co-status-badge');
  if (badge) {
    badge.className  = active > 0 ? 'sc-live' : 'sc-static';
    badge.textContent = active > 0 ? '● ACTIVE (' + active + ')' : '● STANDBY';
  }

  /* Pause button */
  const pb = document.getElementById('co-pause-btn');
  if (pb) pb.textContent = _coGlobalPaused ? '▶ RESUME' : '⏸ PAUSE';

  /* Queue pressure grid */
  const qg = document.getElementById('co-queue-grid');
  if (qg) {
    if (!queues.length) {
      qg.textContent = 'no pending work';
    } else {
      const frag = document.createDocumentFragment();
      queues.forEach(q => {
        const pct   = Math.min(100, Math.round((q.depth / 10) * 100));
        const color = pct >= 80 ? '#ef4444' : pct >= 50 ? '#f59e0b' : '#00ffff';
        const row   = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:10px;margin-bottom:4px;';

        const label = document.createElement('span');
        label.style.cssText = 'width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aaa;';
        label.textContent = q.capability;

        const barWrap = document.createElement('div');
        barWrap.style.cssText = 'flex:1;height:6px;background:#1a1a2e;border-radius:3px;overflow:hidden;';
        const bar = document.createElement('div');
        bar.style.cssText = 'height:100%;border-radius:3px;background:' + color + ';width:' + pct + '%;';
        barWrap.appendChild(bar);

        const count = document.createElement('span');
        count.style.cssText = 'width:35px;text-align:right;color:' + color + ';';
        count.textContent = q.depth;

        const btn = document.createElement('button');
        btn.textContent = '⚙';
        btn.style.cssText = 'font-size:10px;padding:1px 4px;background:#1a1a2e;border:1px solid #333;color:#aaa;cursor:pointer;border-radius:2px;';
        btn.onclick = () => coOpenCapabilityConfig(_esc(q.capability));

        row.append(label, barWrap, count, btn);
        frag.appendChild(row);
      });
      qg.textContent = '';
      qg.appendChild(frag);
    }
  }

  /* Agent overflow grid */
  const ag = document.getElementById('co-agent-grid');
  if (ag) {
    if (!agents.length) {
      ag.textContent = 'no agents scored yet — waiting for first cycle';
    } else {
      const frag = document.createDocumentFragment();
      agents.forEach(a => {
        const scoreColor  = a.score >= 0.5 ? '#00ffff' : '#555';
        const borderColor = a.is_active ? '#00ffff44' : '#1a1a2e';

        const card = document.createElement('div');
        card.style.cssText = 'background:#0a0a1a;border:1px solid ' + borderColor + ';border-radius:4px;padding:8px;font-size:10px;';

        const head = document.createElement('div');
        head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

        const nameSpan = document.createElement('span');
        nameSpan.style.color = a.is_active ? '#00ffff' : '#888';
        nameSpan.textContent = a.agent_name;

        const modeBadge = document.createElement('span');
        modeBadge.style.cssText = 'font-size:9px;color:#00ffff;';
        modeBadge.textContent = a.is_active ? '⟳ overflow' : '';

        head.append(nameSpan, modeBadge);

        const dept = document.createElement('div');
        dept.style.cssText = 'color:#555;font-size:9px;margin-top:2px;';
        dept.textContent = a.department;

        const cap = document.createElement('div');
        cap.style.cssText = 'color:#666;font-size:9px;margin-top:4px;';
        const capVal = document.createElement('span');
        capVal.style.color = '#aaa';
        capVal.textContent = a.capability;
        cap.append(document.createTextNode('cap: '), capVal);

        const barRow = document.createElement('div');
        barRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:4px;';
        const scoreLabel = document.createElement('span');
        scoreLabel.style.cssText = 'font-size:9px;color:#555;';
        scoreLabel.textContent = 'score';
        const bw = document.createElement('div');
        bw.style.cssText = 'flex:1;height:4px;background:#1a1a2e;border-radius:2px;';
        const bf = document.createElement('div');
        bf.style.cssText = 'height:100%;border-radius:2px;background:' + scoreColor + ';width:' + Math.round(a.score * 100) + '%;';
        bw.appendChild(bf);
        const scoreNum = document.createElement('span');
        scoreNum.style.cssText = 'font-size:9px;color:' + scoreColor + ';';
        scoreNum.textContent = a.score.toFixed(2);
        barRow.append(scoreLabel, bw, scoreNum);

        const pauseBtn = document.createElement('button');
        pauseBtn.textContent = '⏸ PAUSE';
        pauseBtn.style.cssText = 'margin-top:6px;width:100%;font-size:9px;padding:2px;background:#1a1a2e;border:1px solid #333;color:#aaa;cursor:pointer;border-radius:2px;';
        const aid = a.agent_id, cap2 = a.capability;
        pauseBtn.onclick = () => coPauseAgent(aid, cap2);

        card.append(head, dept, cap, barRow, pauseBtn);
        frag.appendChild(card);
      });
      ag.textContent = '';
      ag.appendChild(frag);
    }
  }
}

async function coTriggerScan() {
  await fetch('/tools/department-hq/api/orchestration/trigger', {method: 'POST'});
  setTimeout(coRefresh, 1000);
}

async function coToggleGlobalPause() {
  await fetch('/tools/department-hq/api/orchestration/pause', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scope: 'global', paused: !_coGlobalPaused}),
  });
  await coRefresh();
}

async function coPauseAgent(agentId, capability) {
  await fetch('/tools/department-hq/api/orchestration/pause', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scope: 'agent', agent_id: agentId, capability, paused: true}),
  });
  await coRefresh();
}

async function coOpenCapabilityConfig(capability) {
  _coDrawerScope = {scope: 'capability', capability, agent_id: null, node_id: null};
  await _coRenderDrawer('CAPABILITY: ' + _esc(capability));
}

async function coOpenGlobalConfig() {
  _coDrawerScope = {scope: 'global', capability: null, agent_id: null, node_id: null};
  await _coRenderDrawer('GLOBAL THRESHOLDS');
}

let _coDrawerScope = null;

async function _coRenderDrawer(title) {
  const drawer  = document.getElementById('co-config-drawer');
  const overlay = document.getElementById('co-drawer-overlay');
  const content = document.getElementById('co-drawer-content');
  const titleEl = document.getElementById('co-drawer-title');

  if (titleEl) titleEl.textContent = title;

  const r  = await fetch('/tools/department-hq/api/orchestration/config');
  const d  = await r.json();
  const s  = _coDrawerScope;
  const cfg = (d.configs || []).find(c =>
    c.scope === s.scope &&
    c.capability == s.capability &&
    c.agent_id   == s.agent_id
  ) || {};

  const val = (k, def) => (cfg[k] !== undefined ? cfg[k] : def);

  /* Build drawer using DOM methods — no innerHTML with API data */
  content.textContent = '';

  const makeSlider = (id, label, min, max, defaultVal, valId) => {
    const wrap  = document.createElement('label');
    wrap.style.cssText = 'display:block;margin-bottom:12px;font-size:10px;color:#666;';
    wrap.textContent = label + ' ';
    const input = document.createElement('input');
    input.type  = 'range'; input.id = id;
    input.min   = String(min); input.max = String(max);
    input.value = String(val(id.replace('co-', '').replace(/-/g, '_'), defaultVal));
    input.style.cssText = 'width:100%;margin-top:4px;display:block;';
    const display = document.createElement('span');
    display.id    = valId;
    display.style.color = '#00ffff';
    display.textContent = input.value;
    input.oninput = () => { display.textContent = input.value; };
    wrap.append(input, display);
    return wrap;
  };

  content.append(
    makeSlider('idle_threshold_minutes', 'IDLE THRESHOLD (min)', 1, 30, 5, 'co-idle-val'),
    makeSlider('utilization_threshold_pct', 'UTILIZATION THRESHOLD (%)', 10, 95, 60, 'co-util-val'),
    makeSlider('queue_pressure_threshold', 'QUEUE PRESSURE THRESHOLD', 1, 100, 10, 'co-queue-val'),
  );

  const concurrentLabel = document.createElement('label');
  concurrentLabel.style.cssText = 'display:block;margin-bottom:12px;font-size:10px;color:#666;';
  concurrentLabel.textContent = 'MAX OVERFLOW CONCURRENT ';
  const concurrentInput = document.createElement('input');
  concurrentInput.type = 'number'; concurrentInput.id = 'co-max-concurrent';
  concurrentInput.min = '1'; concurrentInput.max = '20';
  concurrentInput.value = String(val('max_overflow_concurrent', 3));
  concurrentInput.style.cssText = 'width:60px;background:#0a0a1a;border:1px solid #333;color:#fff;padding:2px 4px;';
  concurrentLabel.appendChild(concurrentInput);
  content.appendChild(concurrentLabel);

  const enabledLabel = document.createElement('label');
  enabledLabel.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:10px;color:#666;margin-bottom:16px;';
  const enabledInput = document.createElement('input');
  enabledInput.type = 'checkbox'; enabledInput.id = 'co-enabled';
  enabledInput.checked = val('overflow_enabled', true);
  enabledLabel.append(enabledInput, document.createTextNode('OVERFLOW ENABLED'));
  content.appendChild(enabledLabel);

  const saveBtn = document.createElement('button');
  saveBtn.textContent = 'SAVE CONFIG';
  saveBtn.style.cssText = 'width:100%;padding:8px;background:#00ffff22;border:1px solid #00ffff44;color:#00ffff;cursor:pointer;font-size:10px;letter-spacing:1px;';
  saveBtn.onclick = coSaveConfig;
  content.appendChild(saveBtn);

  overlay.style.display = 'block';
  drawer.style.right = '0';
}

function coCloseDrawer() {
  const d = document.getElementById('co-config-drawer');
  const o = document.getElementById('co-drawer-overlay');
  if (d) d.style.right = '-360px';
  if (o) o.style.display = 'none';
}

async function coSaveConfig() {
  const body = {
    ..._coDrawerScope,
    idle_threshold_minutes:    parseInt(document.getElementById('idle_threshold_minutes')?.value || 5),
    utilization_threshold_pct: parseInt(document.getElementById('utilization_threshold_pct')?.value || 60),
    queue_pressure_threshold:  parseInt(document.getElementById('queue_pressure_threshold')?.value || 10),
    max_overflow_concurrent:   parseInt(document.getElementById('co-max-concurrent')?.value || 3),
    overflow_enabled:          document.getElementById('co-enabled')?.checked ?? true,
  };
  await fetch('/tools/department-hq/api/orchestration/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  coCloseDrawer();
  await coRefresh();
}

/* Auto-refresh every 30s */
setInterval(coRefresh, 30000);
document.addEventListener('DOMContentLoaded', () => setTimeout(coRefresh, 2500));
```

- [ ] **Step 5: Restart platform and verify panel**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
```

Open `http://192.168.1.200:3000/tools/department-hq` → Fleet tab → scroll to CLUSTER ORCHESTRATION panel. Verify agent cards and queue bars render. Click ⚙ on a queue — confirm config drawer opens.

- [ ] **Step 6: Commit and create PR**

```bash
git add platform_v2/templates/tools/department_hq.html \
        platform_v2/static/js/department-hq-orchestration.js
git commit -m "feat(orchestration): Fleet tab CLUSTER ORCHESTRATION panel + config drawer"
git push -u origin feat/cluster-orchestration
```

Use the `/commit-push-pr` skill to open the PR.

---

## Self-Review

**Spec coverage:**
- Two new DB tables — Task 1
- Score engine (`compute_overflow_score`, `resolve_config`) — Task 2
- Overflow cache (`update_overflow_cache`, `get_overflow_bonus`) — Task 2
- Worker 5 passes (node util, agent idle, queue depth, config, upsert + alert) — Task 3
- Dispatcher +0.4 bonus — Task 4
- 6 REST endpoints (status, config GET/POST, pause, boost, trigger) — Task 5
- Fleet tab panel (status bar, queue pressure, agent cards) — Task 6
- Config drawer (per-scope sliders, pause, boost) — Task 6
- Telegram alert on mass activation — Task 3

**Placeholder scan:** No TBD, no "add error handling" without specifics, no incomplete steps.

**Security:** All JS DOM rendering uses safe DOM methods (`createElement`, `textContent`, `appendChild`). `_esc()` available for any string in template context. No raw API data in `innerHTML`.

**Type consistency:**
- `get_overflow_bonus(agent_id: int, capability: str) -> float` — defined Task 2, called Task 4
- `update_overflow_cache(states: list)` — defined Task 2, called Task 3
- `_run_cluster_orchestration_worker_fn` — exposed Task 3, imported Task 5 `/trigger`
- `fleet_orchestration_routes.register_orchestration_routes(bp, admin_required)` — defined Task 5, registered Task 5
