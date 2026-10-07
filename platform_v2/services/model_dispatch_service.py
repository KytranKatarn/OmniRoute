"""Model-Affinity Dispatch Queue Worker (Project #304, ADR-004).

Department HQ orchestrates all agent requests through a centralized queue.
This worker drains the queue by routing tasks to wherever the required model
is already warm — hub GPU, hub CPU, or fleet nodes.

Flow (every 15 seconds):
  1. Check what models are loaded on hub + online fleet nodes
  2. Claim + execute queued tasks whose model is already warm
  3. If nothing warm matches the queue, load the highest-priority model batch
  4. Expire stale tasks past their TTL

All products (platform, KBS, WTF, Watch series, apps) enqueue via
dispatch_pending_queue. This worker is the single consumer.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests
from database import get_db_cursor
from psycopg2.extras import RealDictCursor

log = logging.getLogger("platform.model_dispatch")

# Max tasks claimed per model per node per cycle
MAX_TASKS_PER_MODEL = 8
# Max total tasks dispatched per cycle across all models + nodes
MAX_TASKS_PER_CYCLE = 20
# Guaranteed per-cycle drain slice for tasks pinned to a fleet node (kin_warmth
# warmups + cold-load-acceptable pinned work). Pinned tasks run on the NODE's
# Ollama, not hub RAM, so reserve a floor even when the unpinned queue has filled
# MAX_TASKS_PER_CYCLE — otherwise the pinned drain is skipped forever under load
# and fleet warmups starve → expire unclaimed → warm-keep never lands (#3804/#375).
PINNED_RESERVED_SLICE = 2

# #6749: the unpinned queue must always be able to make SOME forward progress.
# PINNED_RESERVED_SLICE is subtracted from free_slots, so with a 6-thread pool and
# 4+ threads in flight — the normal state — `free_slots - PINNED_RESERVED_SLICE`
# is <= 0 and the unpinned drain claimed NOTHING. Measured 2026-09-13: a budget of
# exactly 0 in 15 of 24 consecutive cycles, while a lane sat 133 minutes unclaimed.
# That is a cliff, not a gradient: the reserve silently became a total block.
UNPINNED_MIN_SLICE = 1
# Thread pool for concurrent CPU-model dispatches (prevents blocking the worker thread)
_CPU_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="mdw_cpu")

# Dedicated single-thread executor for background model re-pulls (_heal_pull_model).
# A pull legitimately runs up to 40 minutes (timeout=2400) — sharing _CPU_EXECUTOR
# meant one slow fleet pull ate a drain thread for the duration and starved the
# queue (#5699). One thread also serialises pulls, which is the right bandwidth cap.
_HEAL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mdw_heal")

# Futures still in flight from previous cycles (#5699). The worker used to block the
# scheduler slot on two sequential 300s as_completed() barriers, turning a 15s job
# into 5-12 minute cycles — with max_instances=1 + coalesce=True every fire during a
# long cycle was silently skipped (926 skips/72h) and effective cadence collapsed.
# Worse, it claimed up to MAX_TASKS_PER_CYCLE=20 rows into a 6-thread pool, flipping
# rows to 'running' that never got a thread — they rotted until the 900s reaper.
# Now each cycle claims ONLY what the pool can actually start (free threads) and
# returns immediately; results/errors are handled by a done-callback. Double-claim
# is impossible regardless: _claim_tasks only claims status='queued'.
_INFLIGHT: set = set()

# Fallback TTL (minutes) for capability='warmup' rows that arrive without an
# expires_at. kin_warmth enqueues with a 12-minute TTL; this backstop keeps warmup
# noise minutes-scale so it can never sit long enough to pollute the 2h
# "no drain worker" reaper bucket (#5699 item 3 — all 1,791 historic 'expired'
# rows were warmup). Tunable via platform_settings 'dispatch:warmup_ttl_min'.
WARMUP_TTL_MIN_DEFAULT = 15


def _executor_free_slots() -> int:
    """Prune finished futures and return the number of free _CPU_EXECUTOR threads."""
    for fut in [f for f in _INFLIGHT if f.done()]:
        _INFLIGHT.discard(fut)
    return max(0, _CPU_EXECUTOR._max_workers - len(_INFLIGHT))


def _unpinned_budget(free_slots: int) -> int:
    """How many unpinned rows may be claimed this cycle (#6749).

    The pinned reserve (#3804) exists so a sustained unpinned queue cannot starve
    fleet warm-keeps. It was implemented as a flat subtraction, which on a 6-thread
    pool means the UNPINNED side hits zero first and stays there — the opposite
    starvation, and the one measured in #6749.

    Rule: honour the reserve whenever the pool has room for both, but never let it
    drive the unpinned budget to zero while a thread is actually free.

    CRITICAL: when `free_slots` is 0 the budget stays 0. Claiming a row flips it to
    'running'; a row claimed with no thread to start it rots until the 900s reaper,
    which is the exact defect #5699 fixed. Forward progress never justifies claiming
    into a full pool.
    """
    budget = min(MAX_TASKS_PER_CYCLE, max(0, int(free_slots) - PINNED_RESERVED_SLICE))
    if budget == 0 and int(free_slots) > 0:
        return min(UNPINNED_MIN_SLICE, int(free_slots))
    return budget


def _on_task_done(fut) -> None:
    """Done-callback: drop from the in-flight set and surface exceptions."""
    _INFLIGHT.discard(fut)
    try:
        fut.result()
    except Exception as exc:
        log.warning("model_dispatch: task execution raised: %s", exc)


def _submit_task(task: dict, node_id=None):
    """Submit a claimed task to the pool with in-flight tracking (#5699)."""
    fut = _CPU_EXECUTOR.submit(_execute_task, task, node_id)
    _INFLIGHT.add(fut)
    fut.add_done_callback(_on_task_done)
    return fut


# ── Helpers ──────────────────────────────────────────────────────────────────


def get_pending_queue_result(queue_id: int) -> Optional[dict]:
    """Read a dispatch_pending_queue row's terminal-relevant fields.

    Returns ``{'status', 'result_response', 'error'}`` for the row, or ``None`` if
    the row is absent. Lets queue-tolerant scheduled jobs (e.g.
    warden_compliance_check) await a cold-model dispatch through the service layer
    that owns dispatch_pending_queue, instead of issuing raw SQL from the job.
    Read-only; never commits.
    """
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT status, result_response, error FROM dispatch_pending_queue WHERE id = %s",
            (queue_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):  # RealDictCursor
        return {
            "status": row.get("status"),
            "result_response": row.get("result_response"),
            "error": row.get("error"),
        }
    return {"status": row[0], "result_response": row[1], "error": row[2]}


def _get_warm_models_hub() -> set[str]:
    """Return set of model names currently loaded on hub Ollama."""
    try:
        from services.agent_models import get_loaded_models

        loaded = get_loaded_models()
        return {m["name"] for m in loaded} if loaded else set()
    except Exception as exc:
        log.debug("model_dispatch: hub warm-model check failed: %s", exc)
        return set()


def _get_warm_models_nodes() -> dict[str, int]:
    """Return {model_name: node_db_id} for models available on online fleet nodes.

    Queries node_ollama_models (authoritative source populated by registration
    and heartbeat) joined with remote_nodes. First model wins per name so hub
    gets priority when the same model is warm on both hub and a fleet node.
    """
    result: dict[str, int] = {}
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT rn.id, m.model_name
                FROM node_ollama_models m
                JOIN remote_nodes rn ON rn.node_id = m.node_id
                WHERE rn.is_active = TRUE
                  AND rn.last_heartbeat > NOW() - INTERVAL '3 minutes'
                  AND rn.ollama_available = TRUE
                  AND m.is_available = TRUE
                -- CAPACITY BEFORE PRIORITY (#PR-followup, 2026-10-02).
                -- Starbase IS the hub (mesh_ip=host.docker.internal) and carries the
                -- highest bridge_priority, so the old ordering gave it every warm-model
                -- lookup whether it was idle or pinned at max_concurrent. Work then
                -- queued behind a saturated GPU and died at the 600s dispatch timeout
                -- -- 94 of 200 code_review timeouts in 7d were on that host.
                --
                -- The first key is a BOOLEAN, not a ratio: a node at or over
                -- current_load >= max_concurrent sorts AFTER every node with room,
                -- whatever its priority. Only once Starbase is full does Defiant
                -- (bridge_priority 50) or Runabout (50) become first choice.
                --
                -- Deliberately SOFT: a saturated node still appears, just last. A hard
                -- `current_load < max_concurrent` filter would starve the queue outright
                -- when every node is full, which is a worse failure than queuing.
                ORDER BY (rn.current_load >= rn.max_concurrent) ASC,
                         rn.bridge_priority DESC,
                         rn.current_load ASC
                """
            )
            for row in cur.fetchall():
                name = row.get("model_name")
                if name and name not in result:
                    result[name] = row["id"]
    except Exception as exc:
        log.debug("model_dispatch: node warm-model check failed: %s", exc)
    return result


def _get_all_warm_nodes_for_models() -> dict[str, list[Optional[int]]]:
    """Return {model_name: [node_id_or_None, ...]} for ALL warm nodes per model.

    None = hub. Enables parallel dispatch to multiple nodes when the same model
    is warm on several nodes simultaneously — each gets its own task batch instead
    of first-wins monopolising all work for a given model.
    """
    hub_warm = _get_warm_models_hub()
    # DRP guard: on a promoted DR host (ARCHIE_DR_MODE=1) shed inference so the
    # box's RAM/CPU stays with the standby platform + DR replica + watch products.
    # Skip the LOCAL hub models entirely and drop CPU-only nodes below — only
    # reachable GPU nodes keep serving; if none are reachable the queue simply
    # waits (survival mode). Citadel/boston-2 is the DR base, so this is "Citadel
    # sheds inference so failover gets the full box".
    dr_mode = os.getenv("ARCHIE_DR_MODE", "0") == "1"
    result: dict[str, list] = {} if dr_mode else {m: [None] for m in hub_warm}  # None = hub
    # Capacity gate (#2516 / ADR-555): a model is only routed to a node that can
    # actually hold it. Without this the warm-filter (is_available = PULLED) sends
    # 7B onto 8GB CPU outposts that cold-load to disk and time out 'no result';
    # with Bug-B warm-boot it would instead *flood* them. Uses the FIT-only
    # predicate so the noisy current_load counter can't wrongly disqualify a
    # capable, idle node.
    try:
        from services.fleet_resource_router import can_node_run_model
    except Exception:  # pragma: no cover - fail-open if router import breaks
        can_node_run_model = None
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT rn.id, m.model_name, rn.node_name, rn.deployment_mode,
                       rn.gpu_available, rn.gpu_vram_gb, rn.ram_gb,
                       rn.current_load, rn.gpu_model, rn.extra_capabilities,
                       rn.last_heartbeat
                FROM node_ollama_models m
                JOIN remote_nodes rn ON rn.node_id = m.node_id
                WHERE rn.is_active = TRUE
                  AND rn.last_heartbeat > NOW() - INTERVAL '3 minutes'
                  AND rn.ollama_available = TRUE
                  AND m.is_available = TRUE
                -- Same capacity-before-priority rule as _get_warm_models_nodes: this
                -- query feeds PARALLEL dispatch across every warm node for a model, so
                -- ordering here decides which node leads the batch. A saturated node
                -- must not lead just because it outranks the others.
                ORDER BY (rn.current_load >= rn.max_concurrent) ASC,
                         rn.bridge_priority DESC,
                         rn.current_load ASC
                """
            )
            for row in cur.fetchall():
                name = row.get("model_name")
                if not name:
                    continue
                # DRP guard: in DR mode shed CPU inference (keep GPU nodes only).
                if dr_mode and not row.get("gpu_available"):
                    continue
                # Skip nodes that can't safely hold this model. Fail-open: any
                # error keeps the node (prior behaviour) so a router bug never
                # starves the queue.
                if can_node_run_model is not None:
                    try:
                        if not can_node_run_model(row, name):
                            log.debug(
                                "model_dispatch: %s skipped for %s — capacity gate",
                                row.get("node_name"),
                                name,
                            )
                            continue
                    except Exception:
                        pass
                # The hub (deployment_mode='starbase') is ALSO a remote_nodes row,
                # so it shows up here as a node id (host.docker.internal) on top of
                # the None sentinel from _get_warm_models_hub. Collapse it back to
                # None — deduped + ordered last — so a prefer_gpu 7B is never drained
                # to the hub as a "fleet node" (it would run on the hub's CPU and
                # blow the 300s read-timeout; the #3809 root cause). Hub execution
                # goes through the proven None/hub path.
                lst = result.setdefault(name, [])
                if row.get("deployment_mode") == "starbase":
                    if None not in lst:
                        lst.append(None)
                else:
                    lst.append(row["id"])
    except Exception as exc:
        log.debug("model_dispatch: all-nodes warm-model check failed: %s", exc)

    # Hub-last ordering (#3803 P2b/V8 + #3809 Fix B): the worker drains each model's
    # node list IN ORDER, so the FIRST node claims the tasks. Put the HUB (None) LAST
    # for every multi-node model so fleet nodes drain first and the hub is the
    # last-resort fallback.
    #   * CPU-tier models: keeps small work off the hub (drains to idle outposts).
    #   * prefer_gpu 7B models (#3809): the hub's Quadro M4000 can't hold a 7B
    #     alongside the warm set, so a 7B on the hub runs on CPU and blows the 300s
    #     read-timeout (the F.O.R.G.E. code_review failure). A GPU fleet node (RTX
    #     Starship) MUST drain it first. Previously prefer_gpu kept the hub FIRST,
    #     which is exactly backwards for 7B.
    # Models warm ONLY on the hub (len-1 list, e.g. gemma3:12b that fits nowhere
    # else) are untouched. Fail-open: ordering is best-effort.
    for _nodes in result.values():
        _order_nodes_hub_last(_nodes)
    return result


def _order_nodes_hub_last(nodes: list) -> None:
    """In-place: move the hub sentinel (None) to the end of a multi-node list.

    No-op for len<=1 (model warm only on one place — never strand it) or when the
    hub isn't in the list. Pure + side-effect-free besides the in-place reorder, so
    it's unit-testable without the DB.
    """
    if len(nodes) > 1 and None in nodes:
        nodes.remove(None)
        nodes.append(None)


# ── Fleet model reconciliation + auto-heal (2026-05-29) ───────────────────────
# Three inventory sources drift out of sync with what a node's Ollama actually
# holds:
#   • remote_nodes.extra_capabilities.ollama_models  → BridgeDispatcher routing
#   • node_ollama_models.is_available                → model_dispatch_worker
#   • model_load_state / ARMADA panel                → operator visibility
# When a node loses its models (e.g. Windows Docker Desktop volume reset on
# Starship-246, 2026-05-29) the stale lists keep advertising models it no longer
# has, so the dispatcher routes into a 404 black hole and the panel shows wrong
# counts. This reconciler probes each online fleet node's live /api/tags hub-side
# (canonical mesh transport) and makes the DB the truth, then auto-heals
# genuinely-missing *registered* models via /api/pull — tier-gated so we never
# pull a 7B onto a CPU outpost.

_RECONCILE_INTERVAL_SEC = 60
_last_reconcile_ts = 0.0
# Per (node_db_id, model) re-pull cooldown — don't retry a stuck pull every cycle.
_heal_cooldown: dict[str, float] = {}
_HEAL_COOLDOWN_SEC = 1800  # 30 min between heal attempts per node+model
_HEAL_MAX_PER_NODE_PER_CYCLE = 2  # cap concurrent re-pulls per node
# Custom Modelfile models not in the public registry — /api/pull would 404.
_NON_PULLABLE_PREFIXES = (
    "qwen25-classify",
    "qwen2.5-auditor",
    "arctic-embed",
    "dolphin3-8k",
    "mistral-cpu",
    "gemma2-cpu",
    "minicpm-v-cpu",
)
_runtime_unpullable: set[str] = set()


def _node_live_models(mesh_ip: str, port: int) -> Optional[set[str]]:
    """Live model-name set from a node's Ollama /api/tags.

    Returns None if unreachable (distinct from an empty set, which means the
    node is up but holds zero models — the wipe case worth healing).
    """
    try:
        resp = requests.get(f"http://{mesh_ip}:{port}/api/tags", timeout=4)
        if resp.status_code == 200:
            return {m.get("name", "") for m in resp.json().get("models", []) if m.get("name")}
    except Exception as exc:
        log.debug("reconcile: %s:%s /api/tags unreachable: %s", mesh_ip, port, exc)
    return None


def _canonical_model_name(model: str) -> str:
    """Normalize an Ollama model name for comparison. Ollama's /api/tags always
    returns the fully-qualified ``name:tag`` (defaulting to ``:latest``), but a
    model can be registered in node_ollama_models without the tag. Treat the two
    forms as equal so reconcile doesn't false-flag e.g. ``arctic-embed-cpu`` as
    missing when the node reports ``arctic-embed-cpu:latest``."""
    return model if ":" in model else f"{model}:latest"


def _model_is_warm(model: str, warm_by_model: dict) -> bool:
    """Is `model` warm anywhere, comparing BARE and ``:latest`` forms as equal? (#6749)

    The queue stores what the caller asked for (``qwen25-classify``); the warm
    inventory stores what Ollama reports (``qwen25-classify:latest``). A raw
    ``model in warm_by_model`` is therefore False for a model that is resident and
    actively serving — measured 2026-09-12: 91/91 successful executions while the
    drain declared "no warm node has qwen25-classify" on every cycle and fired a
    blocking cold-load for it.

    `_canonical_model_name` already existed for exactly this and was already applied
    at the reconcile site and inside the claim SQL; this membership test was the one
    place it was missing. Only bare<->:latest are equated — qwen2.5:7b and
    qwen2.5:1.5b must never cross-match.
    """
    if not model:
        return False
    if model in warm_by_model:
        return True
    canon = _canonical_model_name(model)
    return any(_canonical_model_name(k) == canon for k in warm_by_model)


def _drain_order(warm_by_model: dict, head_ages: dict) -> list:
    """Warm models ordered by QUEUE PRESSURE — oldest waiting row first (#6749).

    The drain used to walk `warm_by_model.items()` in dict INSERTION order while the
    per-cycle unpinned budget is small (measured: 3, and 0 whenever 4+ of the 6 pool
    threads are busy). Whichever backlogged model happened to sort first took the
    whole budget every cycle and the loop `break`-ed before reaching the rest.
    Measured 2026-09-12: qwen25-classify at position 1 with 183 rows monopolised the
    budget while qwen2.5:1.5b at position 13 was never reached at all — its head
    aged by exactly the wall-clock elapsed for over two hours.

    Ordering by head age makes the most-starved lane go first, so no lane can be
    starved indefinitely by a neighbour's standing backlog. Models with no queued
    work sort LAST (they cost only an empty claim query).

    PURE: takes the inventory and a {canonical_model: head_age_seconds} map, so it is
    unit-testable without a DB. `head_ages` missing a model simply means "no work".
    """

    def sort_key(item):
        # Negated so the LARGEST head age sorts first; no queued work -> +1.0 -> last.
        return -head_ages.get(_canonical_model_name(item[0]), -1.0)

    return sorted(warm_by_model.items(), key=sort_key)


def _queue_head_age_by_model() -> dict:
    """{canonical_model_name: seconds the oldest CLAIMABLE queued row has waited}.

    Mirrors the claim predicate (unpinned + unexpired) so the ordering reflects what
    `_claim_tasks` could actually take. Fail-safe: on any error return {}, which
    makes `_drain_order` degrade to the previous dict ordering rather than stall the
    drain — a broken ordering hint must never be able to stop the queue.
    """
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT model_needed,
                       EXTRACT(EPOCH FROM (NOW() - MIN(queued_at))) AS head_age_s
                FROM dispatch_pending_queue
                WHERE status = 'queued'
                  AND model_needed IS NOT NULL
                  AND preferred_node_id IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
                GROUP BY model_needed
                """
            )
            ages: dict = {}
            for row in cur.fetchall():
                key = _canonical_model_name(row["model_needed"])
                age = float(row["head_age_s"] or 0.0)
                # Two spellings can collapse to one canonical key — keep the oldest.
                ages[key] = max(ages.get(key, 0.0), age)
            return ages
    except Exception as exc:
        log.warning("model_dispatch: queue head-age probe failed (keeping dict order): %s", exc)
        return {}


def _is_pullable(model: str) -> bool:
    if model in _runtime_unpullable:
        return False
    return not any(model.startswith(p) for p in _NON_PULLABLE_PREFIXES)


def _heal_pull_model(mesh_ip: str, port: int, model: str, node_str_id: str, node_db_id: int) -> None:
    """Background re-pull of a missing registered model on a fleet node.

    Runs in _HEAL_EXECUTOR (single-thread — a 40-min pull must never eat a drain
    thread, #5699). On success, flips node_ollama_models.is_available back
    on so dispatch resumes. On a registry error (custom model), records the model
    as unpullable so we stop retrying it.
    """
    try:
        log.warning("reconcile: auto-heal pulling %s on node_db=%s (%s)", model, node_db_id, mesh_ip)
        resp = requests.post(
            f"http://{mesh_ip}:{port}/api/pull",
            json={"name": model},
            timeout=2400,
            stream=True,
        )
        ok = False
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            if evt.get("error"):
                _runtime_unpullable.add(model)
                log.warning("reconcile: %s not pullable on %s: %s", model, mesh_ip, evt.get("error"))
                return
            if evt.get("status") == "success":
                ok = True
        if ok:
            log.info("reconcile: auto-heal restored %s on node_db=%s", model, node_db_id)
            try:
                with get_db_cursor(commit=True) as (_c, cur):
                    cur.execute(
                        "UPDATE node_ollama_models SET is_available = TRUE " "WHERE node_id = %s AND model_name = %s",
                        (node_str_id, model),
                    )
            except Exception:
                pass
    except Exception as exc:
        log.warning("reconcile: auto-heal pull %s on %s failed: %s", model, mesh_ip, exc)


def reconcile_fleet_models() -> None:
    """Sync each online fleet node's advertised models against live /api/tags.

    Authoritative, hub-side. Updates all three inventory sources so the
    dispatcher (BridgeDispatcher + model_dispatch_worker) and the ARMADA panel
    see live truth, then auto-heals genuinely-missing registered models
    (tier-gated, throttled). Hub is excluded — its models are managed via the
    warm-set health check, not the fleet node registry.

    Throttled to probe at most once per _RECONCILE_INTERVAL_SEC; safe to call
    every worker cycle.
    """
    global _last_reconcile_ts
    now = time.time()
    if now - _last_reconcile_ts < _RECONCILE_INTERVAL_SEC:
        return
    _last_reconcile_ts = now

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id, node_id, node_name, mesh_ip, COALESCE(port, 11434) AS port,
                       gpu_available, gpu_vram_gb, ram_gb, current_load,
                       max_concurrent, priority, last_heartbeat,
                       extra_capabilities, deployment_mode
                FROM remote_nodes
                WHERE is_active = TRUE
                  AND status = 'online'
                  AND last_heartbeat > NOW() - INTERVAL '2 minutes'
                  AND mesh_ip IS NOT NULL
                  AND deployment_mode IS DISTINCT FROM 'starbase'
                  AND mesh_ip NOT IN ('host.docker.internal', '127.0.0.1', 'localhost')
                """
            )
            nodes = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        log.warning("reconcile: node list query failed: %s", exc)
        return

    try:
        from services.fleet_resource_router import score_node_for_model
    except Exception:
        score_node_for_model = None  # type: ignore

    for node in nodes:
        node_db_id = node["id"]
        node_str_id = node["node_id"]
        live = _node_live_models(node["mesh_ip"], node["port"])

        if live is None:
            # Unreachable — flag ollama unavailable, leave model lists intact
            # (a brief blip must not erase a node's whole inventory).
            try:
                with get_db_cursor(commit=True) as (_c, cur):
                    cur.execute(
                        "UPDATE remote_nodes SET ollama_available = FALSE WHERE id = %s",
                        (node_db_id,),
                    )
            except Exception:
                pass
            continue

        missing: list[str] = []
        try:
            with get_db_cursor(commit=True) as (_c, cur):
                # 1. Advertised list + availability flag (BridgeDispatcher source)
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET ollama_available = %s,
                        extra_capabilities = jsonb_set(
                            COALESCE(extra_capabilities, '{}'::jsonb),
                            '{ollama_models}', %s::jsonb, true)
                    WHERE id = %s
                    """,
                    (len(live) > 0, json.dumps(sorted(live)), node_db_id),
                )
                # 2. Upsert live models (model_dispatch_worker source)
                for m in live:
                    cur.execute(
                        """
                        INSERT INTO node_ollama_models (node_id, model_name, is_available)
                        VALUES (%s, %s, TRUE)
                        ON CONFLICT (node_id, model_name)
                        DO UPDATE SET is_available = TRUE
                        """,
                        (node_str_id, m),
                    )
                # 3. Registered-but-not-live → mark unavailable; collect for heal
                cur.execute(
                    "SELECT model_name FROM node_ollama_models WHERE node_id = %s",
                    (node_str_id,),
                )
                registered = [r["model_name"] for r in cur.fetchall()]
                # Tag-normalize both sides: a node reports 'arctic-embed-cpu:latest'
                # via /api/tags while the registry may hold the untagged
                # 'arctic-embed-cpu'. Without this they false-flag as missing.
                live_canon = {_canonical_model_name(m) for m in live}
                missing = [m for m in registered if _canonical_model_name(m) not in live_canon]
                if missing:
                    cur.execute(
                        "UPDATE node_ollama_models SET is_available = FALSE "
                        "WHERE node_id = %s AND model_name = ANY(%s)",
                        (node_str_id, missing),
                    )
        except Exception as exc:
            log.warning("reconcile: DB sync failed for %s: %s", node["node_name"], exc)
            continue

        # 4. Auto-heal: re-pull registered models that vanished (tier-gated)
        if not missing:
            continue
        healed = 0
        for m in missing:
            if healed >= _HEAL_MAX_PER_NODE_PER_CYCLE:
                break
            if not _is_pullable(m):
                continue
            if score_node_for_model is not None:
                try:
                    if score_node_for_model(node, m) is None:
                        continue  # model can't fit this node's tier — skip
                except Exception:
                    pass
            key = f"{node_db_id}:{m}"
            if now - _heal_cooldown.get(key, 0) < _HEAL_COOLDOWN_SEC:
                continue
            _heal_cooldown[key] = now
            _HEAL_EXECUTOR.submit(_heal_pull_model, node["mesh_ip"], node["port"], m, node_str_id, node_db_id)
            healed += 1
        log.warning(
            "reconcile: %s missing %d/%d registered models live (healing %d): %s",
            node["node_name"],
            len(missing),
            len(registered),
            healed,
            missing,
        )


# #5372 DIVERT: pool over-fetch factor for profiled (non-auto) claims. Mirrors the
# Fleet Backlog Runner's `slots * 6` (agent_loop.py) — wide enough that a matching
# row buried behind a wall of non-matching ones still surfaces this cycle.
_PROFILE_POOL_FACTOR = 6

# Ollama treats a bare name as ':latest', but the warm inventory registers the
# tagged form. Match both ways so a queue row 'minicpm-v-cpu' is claimed when the
# warm model is 'minicpm-v-cpu:latest' (and vice-versa). Only equates
# bare<->:latest — does NOT cross-match other tags (qwen2.5:7b vs qwen2.5:1.5b
# stay distinct). (#3469)
_MODEL_MATCH_SQL = """(model_needed = %s
                           OR model_needed = %s || ':latest'
                           OR model_needed || ':latest' = %s)"""


def _get_profile_mode() -> str:
    try:
        from services.fleet_dispatch_profile import get_dispatch_mode

        return get_dispatch_mode()
    except Exception:
        return "auto"


def _get_profile_focus(mode: str) -> str:
    """#6080 AUX POWER: the module-family focus, meaningful only under 'platform'."""
    if mode != "platform":
        return ""
    try:
        from services.fleet_dispatch_profile import get_dispatch_focus

        return get_dispatch_focus()
    except Exception:
        return ""


def _profile_ordered_ids(rows: list[dict], mode: str, limit: int) -> list[int]:
    """#5372: stable-split a claim pool under the active mobility profile.

    Profile-matching rows first, DB order (priority DESC, queued_at ASC)
    preserved WITHIN each group, then truncate to `limit`. This is a SPLIT,
    never a filter: a non-matching row still drains — it only yields its slot
    when a matching row is queued behind it. Fail-open: any error falls back
    to the plain priority order (byte-identical to the pre-#5372 drain).
    """
    try:
        from services.fleet_dispatch_profile import queue_row_gets_priority

        focus = _get_profile_focus(mode)  # #6080 AUX POWER — '' unless platform+focus set
        tagged = [(r, queue_row_gets_priority(r.get("capability"), r.get("module_id"), mode, focus)) for r in rows]
        ordered = [r for r, p in tagged if p] + [r for r, p in tagged if not p]
        n_match = sum(1 for _, p in tagged if p)
        if 0 < n_match < len(tagged):
            log.info(
                "model_dispatch: profile=%s promoted %d/%d queued row(s) in claim pool (#5372)",
                mode,
                n_match,
                len(tagged),
            )
        return [r["id"] for r in ordered[:limit]]
    except Exception as exc:
        log.warning("model_dispatch: profile split failed (%s) — plain priority order", exc)
        return [r["id"] for r in rows[:limit]]


def _claim_ids(cur, ids: list[int]) -> list[dict]:
    """Claim exactly `ids` (already locked by the pool SELECT) and return them
    in the profile order — the drain executes the claimed batch in list order."""
    if not ids:
        return []
    cur.execute(
        """
        UPDATE dispatch_pending_queue
        SET status = 'running', claimed_at = NOW()
        WHERE id = ANY(%s)
        RETURNING *
        """,
        (ids,),
    )
    claimed = [dict(r) for r in cur.fetchall()]
    pos = {tid: i for i, tid in enumerate(ids)}
    claimed.sort(key=lambda r: pos.get(r["id"], len(ids)))
    return claimed


def _claim_tasks(model_needed: str, limit: int = MAX_TASKS_PER_MODEL) -> list[dict]:
    """Atomically claim up to `limit` queued tasks for a given model.

    Under a non-auto mobility profile (#5372) the claim over-fetches a locked
    pool in pure priority order, stable-splits it via
    fleet_dispatch_profile.queue_row_gets_priority, and claims only the top
    `limit` — so the DIVERT profile finally reaches the queue drain, not just
    warmth/routing/backlog. `auto` keeps the original single-statement claim.
    """
    mode = _get_profile_mode()
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            if mode != "auto":
                cur.execute(
                    f"""
                    SELECT id, capability, module_id FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND {_MODEL_MATCH_SQL}
                      AND preferred_node_id IS NULL
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY priority DESC, queued_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (model_needed, model_needed, model_needed, limit * _PROFILE_POOL_FACTOR),
                )
                pool = [dict(r) for r in cur.fetchall()]
                return _claim_ids(cur, _profile_ordered_ids(pool, mode, limit))
            cur.execute(
                f"""
                UPDATE dispatch_pending_queue
                SET status = 'running', claimed_at = NOW()
                WHERE id IN (
                    SELECT id FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND {_MODEL_MATCH_SQL}
                      AND preferred_node_id IS NULL
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY priority DESC, queued_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (model_needed, model_needed, model_needed, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        log.error("model_dispatch: claim_tasks failed for %s: %s", model_needed, exc)
        return []


def _claim_preferred_node_tasks(limit: int = 2) -> list:
    """Claim tasks pinned to a fleet node regardless of warm-model state.

    These tasks bypass the warm-model filter — the node will cold-load the
    model if needed. Capped at 2/cycle to avoid starving hub warm tasks.
    Under a non-auto mobility profile this applies the same #5372 stable-split
    as _claim_tasks (pool over-fetch → profile split → claim top `limit`).

    #5332: while the Starships are UNDOCKED, tasks pinned to a starship are
    LEFT QUEUED (not claimed) so they drain naturally after redock, instead of
    being claimed and then failing/waking a resting ship.
    """
    _skip_starships = False
    try:
        from tools.department_hq.fleet_helpers import is_starships_undocked

        _skip_starships = is_starships_undocked()
    except Exception:
        pass  # fail-open
    mode = _get_profile_mode()
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            if mode != "auto":
                # #5372: same stable-split as _claim_tasks — pinned rows too.
                cur.execute(
                    """
                    SELECT id, capability, module_id FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND preferred_node_id IS NOT NULL
                      AND (expires_at IS NULL OR expires_at > NOW())
                      AND (%s = FALSE OR preferred_node_id NOT IN (
                            SELECT id FROM remote_nodes WHERE deployment_mode = 'starship'))
                    ORDER BY priority DESC, queued_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (_skip_starships, limit * _PROFILE_POOL_FACTOR),
                )
                pool = [dict(r) for r in cur.fetchall()]
                return _claim_ids(cur, _profile_ordered_ids(pool, mode, limit))
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                SET status = 'running', claimed_at = NOW()
                WHERE id IN (
                    SELECT id FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND preferred_node_id IS NOT NULL
                      AND (expires_at IS NULL OR expires_at > NOW())
                      AND (%s = FALSE OR preferred_node_id NOT IN (
                            SELECT id FROM remote_nodes WHERE deployment_mode = 'starship'))
                    ORDER BY priority DESC, queued_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (_skip_starships, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        log.error("model_dispatch: claim_preferred_node_tasks failed: %s", exc)
        return []


def _mark_done(task_id: int, response: str, model_used: str, tokens: int, node_id: Optional[int]) -> None:
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                SET status = 'done',
                    completed_at = NOW(),
                    result_response = %s,
                    result_model_used = %s,
                    result_tokens = %s,
                    result_node_id = %s
                WHERE id = %s
                """,
                (response, model_used, tokens, node_id, task_id),
            )
            _handle_callback(cur, task_id, response)
    except Exception as exc:
        log.error("model_dispatch: mark_done failed for task %d: %s", task_id, exc)


def _mark_failed(task_id: int, error: str) -> None:
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                SET status = 'failed', completed_at = NOW(), error = %s
                WHERE id = %s
                """,
                (error[:500], task_id),
            )
            _handle_failure_callback(cur, task_id, error)
    except Exception as exc:
        log.error("model_dispatch: mark_failed failed for task %d: %s", task_id, exc)


def _requeue_cold(task_id: int, model: str, where: str) -> None:
    """Model still COLD at execute time → return the task to 'queued' to retry a later
    cycle (WTF 'ready-or-queue' standard) instead of failing it 'no result'.

    The node warm-filter (node_ollama_models.is_available) means PULLED, not LOADED, so a
    claimed node task can still be cold. Rather than dispatch-into-a-cold-model and fail,
    we re-queue; the next cycle's load step (or ensure_model_ready) warms it, then it
    drains successfully. ``expires_at`` bounds the retries so this never loops forever.
    Only re-queues a row we still hold ('running')."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE dispatch_pending_queue SET status='queued', claimed_at=NULL "
                "WHERE id=%s AND status='running'",
                (task_id,),
            )
        log.info("model_dispatch: task #%d re-queued — %s still cold-loading on %s", task_id, model, where)
    except Exception as exc:
        log.error("model_dispatch: requeue failed for #%d: %s", task_id, exc)


def _handle_failure_callback(cur: RealDictCursor, task_id: int, error: str) -> None:
    """Notify a delegation task that its queued dispatch failed/expired.

    Layer-3 (#269999): without this, a delegation deferred to the cold-load
    queue that then fails (or expires) orphans its unified_task in
    'in_progress' forever. Mirrors delegation_service.mark_task_failed
    (status='blocked' + delegation_failure note). Only fires for
    ``delegation_result`` callbacks — other callback types are unaffected.
    """
    try:
        cur.execute(
            "SELECT callback_type, callback_data FROM dispatch_pending_queue WHERE id = %s",
            (task_id,),
        )
        row = cur.fetchone()
        if not row or row.get("callback_type") != "delegation_result":
            return
        import json as _json

        cb = row.get("callback_data") or {}
        tid = cb.get("task_id")
        if not tid:
            return
        cur.execute(
            "UPDATE unified_tasks SET status = 'blocked' WHERE id = %s",
            (tid,),
        )
        cur.execute(
            """
            INSERT INTO work_notes (task_id, note_type, content, metadata)
            VALUES (%s, 'delegation_failure', %s, %s::jsonb)
            """,
            (
                tid,
                f"Fleet cold-load queue #{task_id} failed: {(error or '')[:300]}",
                _json.dumps({"outcome": "blocked", "via": "queue_callback", "queue_id": task_id}),
            ),
        )
    except Exception as exc:
        log.error("model_dispatch: failure callback for task %d failed: %s", task_id, exc)


def _handle_callback(cur: RealDictCursor, task_id: int, response: str) -> None:
    """Fire callback if task requested one (runs inside existing transaction)."""
    try:
        cur.execute(
            "SELECT callback_type, callback_data FROM dispatch_pending_queue WHERE id = %s",
            (task_id,),
        )
        row = cur.fetchone()
        if not row or not row["callback_type"]:
            return

        cb_type = row["callback_type"]
        cb_data = row["callback_data"] or {}

        if cb_type == "task_result":
            task_id_target = cb_data.get("task_id")
            if task_id_target:
                cur.execute(
                    "UPDATE unified_tasks SET work_notes = %s, status = 'completed' WHERE id = %s",
                    (response[:2000], task_id_target),
                )
        elif cb_type == "delegation_result":
            # Layer-3 (#269999): a Claude/automation delegation that was deferred
            # to this cold-load queue finished. Write the output back to its
            # unified_task (work_notes TABLE — mirrors
            # delegation_service.mark_task_completed) and mark it completed,
            # instead of leaving it orphaned in_progress.
            import json as _json

            tid = cb_data.get("task_id")
            if tid:
                # #4167: surface the delegated output onto the unified_task (not
                # just the work_notes table) + flag code-as-advisory, mirroring
                # the sync path (delegation_service.mark_task_completed). Local
                # import avoids a module-load circular import.
                from services.delegation_service import build_delegation_metadata

                cap = cb_data.get("capability")
                deleg_meta = build_delegation_metadata(cap, response, outcome="completed", via="queue_callback")
                cur.execute(
                    "UPDATE unified_tasks "
                    "SET status = 'completed', completed_at = now(), "
                    "    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('delegation', %s::jsonb) "
                    "WHERE id = %s",
                    (_json.dumps(deleg_meta), tid),
                )
                note = f"Completed via fleet cold-load queue #{task_id} (async)"
                if deleg_meta.get("advisory"):
                    note = f"⚠️ {deleg_meta['advisory']}\n\n{note}"
                cur.execute(
                    """
                    INSERT INTO work_notes (task_id, note_type, content, metadata)
                    VALUES (%s, 'delegation_result', %s, %s::jsonb)
                    """,
                    (
                        tid,
                        note,
                        _json.dumps({"outcome": "completed", "via": "queue_callback", "queue_id": task_id}),
                    ),
                )
                resp = (response or "").strip()
                if resp:
                    cur.execute(
                        """
                        INSERT INTO work_notes (task_id, note_type, content, metadata)
                        VALUES (%s, 'delegation_output', %s, %s::jsonb)
                        """,
                        (
                            tid,
                            resp[:20000],
                            _json.dumps({"outcome": "completed", "chars": len(resp), "via": "queue_callback"}),
                        ),
                    )
        elif cb_type == "pr_review_result":
            # A queued F.O.R.G.E. code_review (model cold-load) finished. Write
            # the verdict back to pr_reviews + flip review_status='reviewed' so
            # the review is no longer stuck pending/queued. Mirrors
            # pr_review_service.mark_review_done's UPDATE, inline (we already
            # hold the cursor/transaction). NO auto-merge from the async path —
            # a PR must not merge itself minutes later; the merge gate stays in
            # the synchronous review flow / human hands.
            pr_number = cb_data.get("pr_number")
            repo = cb_data.get("repo") or "KytranKatarn/archie-platform"
            resp = (response or "").strip()
            if pr_number and resp:
                cur.execute(
                    """
                    UPDATE pr_reviews
                       SET review_status = 'reviewed', ai_summary = %s,
                           ai_review_at = now(), updated_at = now()
                     WHERE pr_number = %s AND repo = %s
                    """,
                    (resp, pr_number, repo),
                )
                # #5780: an UPDATE matching ZERO rows is a SILENT no-op — the review
                # succeeded, the artifact exists, and the verdict is simply dropped. That is
                # invisible today, and the merge gate then fails closed on a missing verdict
                # with no explanation. Make the miss loud; never guess at a repair here.
                if cur.rowcount == 0:
                    log.warning(
                        "model_dispatch: pr_review_result callback matched NO pr_reviews row "
                        "(pr=%s repo=%s, %d chars of verdict DROPPED) — the review ran and its "
                        "result is being lost",
                        pr_number,
                        repo,
                        len(resp),
                    )

        elif cb_type == "webhook":
            # Fire async — don't block the worker cycle
            import json as _json
            import threading
            import urllib.request

            url = cb_data.get("url", "")
            if url:
                payload = _json.dumps({"task_id": task_id, "response": response}).encode()
                threading.Thread(
                    target=lambda: urllib.request.urlopen(
                        urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}),
                        timeout=10,
                    ),
                    daemon=True,
                ).start()

        elif cb_type == "deploy_approve_gate":
            # F.O.R.G.E. / director finished reviewing a deployment proposal.
            # If APPROVED → run sandbox gate (P.R.O.B.E. #79) → deploy to production.
            import threading as _t

            proposal_id = cb_data.get("proposal_id")
            if not proposal_id:
                log.warning("deploy_approve_gate: no proposal_id in callback_data")
                return

            verdict = (response or "").upper()
            from services.repair_submission import approval_response_is_positive

            approved = approval_response_is_positive(verdict)

            def _run_gate_and_deploy():
                try:
                    import sys as _sys

                    _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from services.proposal_service import _sandbox_gate, ship_as_pr
                    from database import get_db_cursor as _gdc
                    import logging as _logging

                    _log = _logging.getLogger(__name__)

                    with _gdc() as (_c, _cur):
                        _cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
                        proposal = _cur.fetchone()

                    if not proposal:
                        _log.error("deploy_approve_gate: proposal #%s not found", proposal_id)
                        return

                    agent_name = cb_data.get("agent_name", "Director")

                    if not approved:
                        from services.repair_submission import update_stage

                        update_stage(proposal_id, "blocked", error="Patch review rejected")
                        _log.info("deploy_approve_gate: #%s REJECTED by %s", proposal_id, agent_name)
                        with _gdc(commit=True) as (_c2, _cur2):
                            _cur2.execute(
                                "UPDATE improvement_proposals SET status='fix_requested' WHERE id=%s AND status NOT IN ('deployed','rejected')",
                                (proposal_id,),
                            )
                        return

                    # Run sandbox gate
                    gate = _sandbox_gate(proposal_id, proposal)
                    if not gate["passed"]:
                        _log.warning(
                            "deploy_approve_gate: sandbox gate FAILED for #%s — %s/%s",
                            proposal_id,
                            gate["passed_count"],
                            gate["total"],
                        )
                        return

                    # Gate passed — ship as a PR (spec 2026-08-26 §6.3: the governed
                    # merge is the apply; skip_gate=True because the gate just ran).
                    result = ship_as_pr(proposal_id, skip_gate=True)
                    _log.info(
                        "deploy_approve_gate: proposal #%s %s after gate %s/%s",
                        proposal_id,
                        "DEPLOYED" if result["success"] else "FAILED",
                        gate["passed_count"],
                        gate["total"],
                    )
                except Exception as _e:
                    import logging as _ll

                    from services.repair_submission import update_stage

                    update_stage(proposal_id, "blocked", error=str(_e)[:300])
                    _ll.getLogger(__name__).error("deploy_approve_gate thread error: %s", _e)

            _t.Thread(target=_run_gate_and_deploy, daemon=True).start()
            log.info(
                "deploy_approve_gate: proposal #%s — verdict=%s — sandbox+deploy thread started",
                proposal_id,
                "APPROVED" if approved else "REJECTED",
            )

        elif cb_type == "proposal_regen":
            # Agent (V.I.G.I.L./F.O.R.G.E./B.A.S.E.) regenerated a better fix.
            # Save response as new code_changes and reset to ready_for_review.
            import threading as _t

            proposal_id = cb_data.get("proposal_id")
            agent_name = cb_data.get("agent_name", "agent")
            if not proposal_id:
                log.warning("proposal_regen: no proposal_id in callback_data")
                return

            def _save_regen():
                try:
                    from database import get_db_cursor as _gdc

                    with _gdc(commit=True) as (_c, _cur):
                        _cur.execute(
                            """UPDATE improvement_proposals
                               SET code_changes = %s,
                                   status = 'ready_for_review',
                                   reviewed_at = NOW()
                               WHERE id = %s AND status IN ('fix_requested','approved','proposed')
                               RETURNING id""",
                            (response, proposal_id),
                        )
                        updated = _cur.fetchone()
                    if updated:
                        log.info(
                            "proposal_regen: #%s fix regenerated by %s → ready_for_review",
                            proposal_id,
                            agent_name,
                        )
                        if cb_data.get("auto_queue_deploy"):
                            try:
                                import sys as _sys

                                _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                                from services.proposal_service import request_tiered_deploy_approval

                                _r = request_tiered_deploy_approval(proposal_id)
                                log.info(
                                    "proposal_regen: #%s auto-queued for deploy approval: %s",
                                    proposal_id,
                                    _r.get("message", "queued"),
                                )
                            except Exception as _de:
                                log.warning(
                                    "proposal_regen: #%s auto-deploy-queue failed: %s",
                                    proposal_id,
                                    _de,
                                )
                    else:
                        log.warning("proposal_regen: #%s not updated (wrong status?)", proposal_id)
                except Exception as _e:
                    import logging as _ll

                    _ll.getLogger(__name__).error("proposal_regen thread error: %s", _e)

            _t.Thread(target=_save_regen, daemon=True).start()
            log.info("proposal_regen: queued save for proposal #%s by %s", proposal_id, agent_name)

    except Exception as exc:
        log.debug("model_dispatch: callback failed for task %d: %s", task_id, exc)


_WARMUP_MODULES = ("fleet_warmup", "kin_warmth")


def _queue_attributed_agent_id(task: dict, module_id: str):
    """agent_id for a queue-drained task_execution_log row: the SELECTED agent carried on
    the queue row (``dispatch_pending_queue.agent_id``), EXCEPT warm-up keep-alive
    (fleet_warmup / kin_warmth) which stays unattributed (None). recal/budget currently
    exclude warm-up ONLY via ``agent_id IS NULL`` (no module_source filter), so attributing
    keep-warm pings to their agent would inflate its budget — whether keep-warm should count
    is the separate 'warm-up pseudo-agent' decision. Returns None when the queue row carries
    no agent_id."""
    if module_id in _WARMUP_MODULES:
        return None
    return task.get("agent_id")


def _log_to_tel(task: dict, result: dict, model_used: str, node_id, duration_ms: int = 0) -> None:
    """Mirror a queue-drained dispatch into task_execution_log (P1.2, #3801).

    The queue worker calls disp._dispatch_to_node()/_execute_llm() DIRECTLY,
    bypassing request_work()/_log_execution — so queue-drained dispatches + their
    tokens never reached TEL and were invisible in Token Economy + ARMADA (~1.4k
    dispatches / ~209k tokens a day). Build a DispatchResult from the raw result
    and reuse the canonical writer so every column + the token-gap instrumentation
    match the sync path. Best-effort: never let logging break the drain.
    """
    try:
        from tools.department_hq.services.department_dispatcher import (
            DispatchResult,
            get_dispatcher,
        )

        prompt_toks = int(result.get("prompt_eval_count") or result.get("prompt_tokens") or 0)
        completion_toks = int(result.get("eval_count") or result.get("completion_tokens") or 0)
        if prompt_toks == 0 and completion_toks == 0:
            completion_toks = int(result.get("tokens_used") or 0)
        # via= tags request_metadata so queue-drained rows are distinguishable
        # from sync dispatch() rows (provenance + verification). node_id (when set)
        # is read by _log_execution for the node_used_id column.
        meta = {"via": "model_dispatch_worker"}
        if node_id is not None:
            meta["node_id"] = node_id
        # duration_ms feeds CO2/energy/avg-ms in A.R.M.A.D.A. + the carbon pillar.
        # The queue worker bypasses request_work(), so without this every drained
        # row logged 0 -> 0 CO2/Wh/avg-ms for ~1.4k real fleet dispatches/day.
        # Prefer the caller's measured wall-clock; fall back to ollama total_duration
        # (ns -> ms) if the caller didn't pass one (defensive).
        dur_ms = int(duration_ms or 0)
        if dur_ms <= 0:
            try:
                _td = int(result.get("total_duration") or 0)
                dur_ms = _td // 1_000_000 if _td > 1_000_000 else _td
            except Exception:
                dur_ms = 0
        # source_product is the meaningful attribution (wtf_hub, wtf_dhq_*, …) so
        # module_source is never a useless "unknown" bucket for queue work.
        module_id = task.get("source_product") or task.get("module_id") or "model_dispatch"
        # Attribute to the SELECTED agent (the queue row carries agent_id) so cold-load
        # queue-drained inference is billed to that agent instead of a NULL agent — the sync
        # path already sets it; this path dropped it, so ~half of drained rows (~1.8M tok/7d)
        # logged agent_id=NULL and were invisible to per-agent budget/welfare/K.I.N.
        # accounting. Warm-up keep-alive is deliberately excluded (see
        # _queue_attributed_agent_id) so recal isn't inflated by keep-warm pings.
        dr = DispatchResult(
            success=True,
            response=result.get("response", "") or "",
            agent_name=task.get("agent_name") or "model_dispatch",
            agent_id=_queue_attributed_agent_id(task, module_id),
            model_used=result.get("model") or model_used,
            capability=task.get("capability", "") or "",
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            provider="ollama",
            duration_ms=dur_ms,
            metadata=meta,
            queued=False,
        )
        get_dispatcher()._log_execution(dr, module_id, task.get("user_id"))
    except Exception as exc:  # never let TEL logging break the drain
        log.debug("model_dispatch: TEL log failed (non-fatal): %s", exc)


def _execute_task(task: dict, node_id: Optional[int] = None) -> None:
    """Run a single queued task through the dispatcher's LLM execution."""
    task_id = task["id"]
    model = task["model_needed"]
    log.info(
        "model_dispatch: executing task #%d (capability=%s model=%s priority=%d source=%s)",
        task_id,
        task.get("capability"),
        model,
        task.get("priority", 5),
        task.get("source_product", "unknown"),
    )
    try:
        # Honour agent's preferred fleet node when warm-model routing didn't pick one.
        # Verify the node is still online before committing — fall back to hub if stale.
        if not node_id and task.get("preferred_node_id"):
            preferred = task["preferred_node_id"]
            try:
                with get_db_cursor() as (_conn, _cur):
                    _cur.execute(
                        """SELECT id FROM remote_nodes
                           WHERE id = %s AND status = 'online'
                             AND last_heartbeat > NOW() - INTERVAL '3 minutes'""",
                        (preferred,),
                    )
                    if _cur.fetchone():
                        node_id = preferred
                    else:
                        log.warning(
                            "model_dispatch: preferred node %d offline — falling back to hub",
                            preferred,
                        )
            except Exception:
                node_id = preferred  # fail-open: attempt dispatch, let _dispatch_to_node surface the error

        if node_id:
            # Route to fleet node. Resolve hostname+port here — _dispatch_to_node
            # uses strict subscript on agent_info["node_port"], so the caller is
            # the resolution authority (matches all other callers in the dispatcher).
            # Prefer mesh_ip for inter-cluster transport per ADR-008 / mesh mandate.
            try:
                with get_db_cursor() as (_conn, _cur):
                    _cur.execute(
                        """SELECT node_name, hostname, mesh_ip, port,
                                  gpu_available, gpu_vram_gb, ram_gb, extra_capabilities
                           FROM remote_nodes WHERE id = %s""",
                        (node_id,),
                    )
                    node_row = _cur.fetchone()
            except Exception as exc:
                log.error("model_dispatch: node lookup failed for id=%s: %s", node_id, exc)
                node_row = None

            if not node_row:
                _mark_failed(task_id, f"remote_nodes row missing for node_id={node_id}")
                return

            node_hostname = node_row.get("mesh_ip") or node_row.get("hostname") or ""
            node_port = node_row.get("port") or 11434
            node_name = node_row.get("node_name") or "unknown"

            # P2a (#3802): capacity gate for the PREFERRED-node path. The general
            # warm-discovery already runs can_node_run_model, but preferred-pinned
            # tasks bypass it — without this a 7B pinned to a CPU node gets
            # warm-booted there (disk-swap -> timeout -> re-queue). Fail the bad
            # pin fast instead. Regular (already-gated) tasks pass as a no-op.
            try:
                from services.fleet_resource_router import can_node_run_model, node_has_model

                if not can_node_run_model(node_row, model):
                    log.warning(
                        "model_dispatch: node %s cannot fit %s — failing pin (capacity)",
                        node_name,
                        model,
                    )
                    _mark_failed(task_id, f"node {node_name} cannot fit {model} (capacity gate)")
                    return
                # PRESENCE, not just capacity (#5863/#5861). Capacity only proves the node
                # COULD hold a model this size; it does not prove THIS model is pulled
                # there. `find_best_node_for_model` already pairs these two predicates on
                # the SELECTION path — the PINNED path checked only capacity, and that is
                # the whole bug: can_node_run_model(USS-245, 'qwen2.5-coder:7b') is True
                # (GPU fit fails, so it falls through to ram_gb 11.7 >= required 8.0 and
                # deems CPU demotion viable) while the model is NOT pulled there. Measured
                # 2026-08-20: 16 dispatches, 0 succeeded, ~0.3s each, MODEL_NOT_FOUND.
                # node_has_model is fail-OPEN (unknown model list => allow), so a stale or
                # missing heartbeat inventory can never starve the queue.
                if not node_has_model(node_row, model):
                    log.warning(
                        "model_dispatch: node %s does not have %s pulled — failing pin (presence)",
                        node_name,
                        model,
                    )
                    _mark_failed(task_id, f"node {node_name} does not have {model} (presence gate)")
                    return
            except Exception:
                pass  # fail-open: never block dispatch on a router import error

            from tools.department_hq.services.department_dispatcher import get_dispatcher

            disp = get_dispatcher()
            # Readiness preflight (WTF 'ready-or-queue' standard): the node warm-filter is
            # is_available=PULLED, not LOADED, so this node may be cold. ensure_model_ready
            # checks the node's live /api/ps (and warms it); if still not ready, RE-QUEUE
            # instead of dispatching into a cold model and failing 'no result'.
            # NOTE: target_host MUST be a dict {"hostname", "port"} — model_service does
            # target_host.get("hostname"); passing a bare string raised
            # "'str' object has no attribute 'get'" on EVERY node preflight, which silently
            # re-queued all node-bound 7B work forever (regression from #1515).
            try:
                _rd = disp.ensure_model_ready(
                    task.get("agent_name") or "model_dispatch",
                    model,
                    {"hostname": node_hostname, "port": node_port},
                )
            except Exception as _re:
                log.warning("model_dispatch: node ensure_model_ready(%s,%s) failed: %s", node_name, model, _re)
                _rd = None
            if not (_rd and _rd.get("ready")):
                _requeue_cold(task_id, model, node_name)
                return
            _t0 = time.time()
            result = disp._dispatch_to_node(
                agent_info={
                    "agent_name": task.get("agent_name", "unknown"),
                    "model": model,
                    "node_id": node_id,
                    "node_hostname": node_hostname,
                    "node_port": node_port,
                    "node_name": node_name,
                },
                prompt=task.get("prompt", ""),
                system_prompt=task.get("system_prompt"),
                options={},
                capability=task.get("capability", ""),
                module_id=task.get("module_id", "model_dispatch"),
                station_code="ENGINEERING",
                user_id=task.get("user_id"),
            )
            if result and result.get("success"):
                # Capture real tokens from the node result instead of hardcoding 0
                # (node-executed queued work previously always logged result_tokens=0).
                node_tokens = (
                    (result.get("prompt_eval_count", 0) + result.get("eval_count", 0))
                    or (result.get("prompt_tokens", 0) + result.get("completion_tokens", 0))
                    or result.get("tokens_used", 0)
                )
                _mark_done(task_id, result.get("response", ""), model, node_tokens, node_id)
                _log_to_tel(task, result, model, node_id, int((time.time() - _t0) * 1000))
            else:
                _mark_failed(task_id, result.get("error", "node dispatch failed") if result else "no result")
        else:
            # Run on hub via dispatcher _execute_llm
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            disp = get_dispatcher()
            # Readiness preflight (WTF standard) — safety net vs the warm→evicted race on
            # the hub. ensure_model_ready returns fast when already loaded; re-queue (not
            # fail) if it can't be made ready.
            try:
                _rd = disp.ensure_model_ready(task.get("agent_name") or "model_dispatch", model, None)
            except Exception as _re:
                log.warning("model_dispatch: hub ensure_model_ready(%s) failed: %s", model, _re)
                _rd = None
            if not (_rd and _rd.get("ready")):
                _requeue_cold(task_id, model, "hub")
                return
            _t0 = time.time()
            result = disp._execute_llm(
                model=model,
                prompt=task.get("prompt", ""),
                system_prompt=task.get("system_prompt"),
                json_mode=task.get("json_mode", False),
                capability=task.get("capability", ""),
                module_id=task.get("module_id", "model_dispatch"),
                agent_name=task.get("agent_name"),
            )
            if result and result.get("success"):
                tokens = result.get("eval_count") or result.get("completion_tokens", 0)
                response = result.get("response", "")
                _mark_done(task_id, response, result.get("model", model), tokens, None)
                _log_to_tel(task, result, result.get("model", model), None, int((time.time() - _t0) * 1000))
                # Pipeline continuation: social draft → translate → Telegram approval
                if task.get("capability") == "social_post_draft" and response:
                    _continue_signal_pipeline(task, response)
            else:
                error = result.get("error", "llm returned failure") if result else "no result"
                _mark_failed(task_id, error)

    except Exception as exc:
        log.error("model_dispatch: task #%d execution failed: %s", task_id, exc)
        _mark_failed(task_id, str(exc)[:500])


def _continue_signal_pipeline(task: dict, english_draft: str) -> None:
    """After a social_post_draft completes: translate via R.O.S.E.T.T.A. then queue for approval.

    Runs in the worker thread — keeps the full S.I.G.N.A.L. pipeline intact
    even when the initial draft was queued due to a cold model.
    """
    import threading

    def _run():
        try:
            import json as _j
            from tools.department_hq.services.department_dispatcher import dispatch

            # Read callback context (post_type, hashtags, language_only)
            cb_raw = task.get("callback_data") or {}
            if isinstance(cb_raw, str):
                try:
                    cb_raw = _j.loads(cb_raw)
                except Exception:
                    cb_raw = {}
            post_type = cb_raw.get("post_type", "personal")
            hashtags = cb_raw.get("hashtags", [])
            language_only = cb_raw.get("language_only", "bilingual")

            # Step 1: translate to Québécois (skip for EN-only posts)
            qc_draft = ""
            if language_only in ("bilingual", "fr"):
                try:
                    t_result = dispatch(
                        capability="translate",
                        prompt=(
                            "Translate this LinkedIn post to Québécois French "
                            "(joual/québécois dialect — NOT France French). "
                            "Keep tone, voice, hashtags, and engagement question.\n\n" + english_draft
                        ),
                        prefer_agent="R.O.S.E.T.T.A.",
                        source_product="archie_platform",
                    )
                    if t_result and t_result.success:
                        qc_draft = (t_result.response or "").strip()
                        log.info("model_dispatch: R.O.S.E.T.T.A. translated draft (%d chars)", len(qc_draft))
                except Exception as te:
                    log.warning("model_dispatch: R.O.S.E.T.T.A. translation failed: %s", te)

            # Step 2: assemble combined draft per language_only setting
            if language_only == "en":
                combined = f"\U0001f1e8\U0001f1e6 English:\n{english_draft}"
            elif language_only == "fr":
                combined = f"⚜️ Français québécois:\n{qc_draft or english_draft}"
            elif qc_draft:
                combined = (
                    f"\U0001f1e8\U0001f1e6 English:\n{english_draft}"
                    f"\n\n---\n\n"
                    f"⚜️ Français québécois:\n{qc_draft}"
                )
            else:
                combined = english_draft

            import sys

            sys.path.insert(0, "/app")
            from ai_bridge.agent_loop import request_approval

            approval_id = request_approval(
                action_type="linkedin_post",
                action_data={
                    "content": combined,
                    "hashtags": hashtags,
                    "post_type": post_type,
                    "browser_agent_id": 342,
                },
                reason=f"📣 S.I.G.N.A.L. LinkedIn draft (via queue):\n\n{combined[:1500]}",
                tier=2,
                requested_by="S.I.G.N.A.L. (model_dispatch_worker)",
                priority=task.get("priority", 5),
            )
            log.info("model_dispatch: signal pipeline complete — approval #%s queued", approval_id)

        except Exception as exc:
            log.error("model_dispatch: signal pipeline continuation failed: %s", exc)

    threading.Thread(target=_run, daemon=True, name="signal-pipeline-cont").start()


def _free_comfyui_vram_if_idle() -> bool:
    """Free ComfyUI VRAM when Pixel has no active generation jobs.

    Offloads ComfyUI models to CPU (container stays running) so Ollama
    text models can use the GPU. Skips if ComfyUI queue is non-empty.
    """
    import json as _json
    import os
    import urllib.request

    comfyui_url = os.getenv("COMFYUI_HOST", "http://host.docker.internal:8188")
    try:
        # Skip if ComfyUI is generating
        with urllib.request.urlopen(f"{comfyui_url}/queue", timeout=3) as r:
            q = _json.loads(r.read())
        if q.get("queue_running") or q.get("queue_pending"):
            log.info("model_dispatch: ComfyUI busy — skipping VRAM free")
            return False

        # Check how much VRAM ComfyUI is holding
        with urllib.request.urlopen(f"{comfyui_url}/system_stats", timeout=3) as r:
            stats = _json.loads(r.read())
        devices = stats.get("devices", [])
        vram_held = sum(d.get("vram_total", 0) - d.get("vram_free", 0) for d in devices)
        if vram_held < 100 * 1024 * 1024:
            return False  # nothing to free

        # Free — offloads to CPU, container stays alive
        payload = _json.dumps({"unload_models": True, "free_memory": True}).encode()
        req = urllib.request.Request(
            f"{comfyui_url}/free",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log.info(
            "model_dispatch: ComfyUI VRAM freed (Pixel idle) — %.1f GB released",
            vram_held / 1e9,
        )
        return True
    except Exception as exc:
        log.debug("model_dispatch: ComfyUI VRAM free skipped: %s", exc)
        return False


def _ensure_ram_for_model(model_name: str) -> bool:
    """Free RAM to make room for model_name by evicting idle loaded models.

    Returns True if there is (or will be) enough RAM after eviction.
    Uses the dispatcher's unload_model() — never calls Ollama directly.
    """
    try:
        from services.agent_models import get_loaded_models
        from services.model_service import ModelService

        svc = ModelService()
        available_gb = svc.get_available_ram()

        # Estimate runtime size from disk size (× 1.35 safety factor)
        needed_gb = 0.0
        try:
            import urllib.request
            import json as _json

            ollama_url = "http://host.docker.internal:11434"
            with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5) as resp:
                tags = _json.loads(resp.read()).get("models", [])
                for m in tags:
                    if m.get("name", "").startswith(model_name.split(":")[0]):
                        needed_gb = round(m.get("size", 0) / 1e9 * 1.35, 2)
                        break
        except Exception:
            needed_gb = 5.0  # conservative default

        if available_gb >= needed_gb:
            # Still check VRAM — free ComfyUI if it's holding the GPU idle
            _free_comfyui_vram_if_idle()
            return True

        # Try freeing ComfyUI VRAM first (faster than evicting Ollama models)
        _free_comfyui_vram_if_idle()

        log.info(
            "model_dispatch: need %.1fGB for %s, have %.1fGB — evicting idle models",
            needed_gb,
            model_name,
            available_gb,
        )

        # Get loaded models sorted by expires_at (most idle = evict first)
        loaded = get_loaded_models()
        loaded_sorted = sorted(loaded, key=lambda m: m.get("expires_at") or "")

        from tools.department_hq.services.department_dispatcher import get_dispatcher

        disp = get_dispatcher()

        freed_gb = 0.0
        for m in loaded_sorted:
            if available_gb + freed_gb >= needed_gb:
                break
            mname = m.get("name", "")
            if mname == model_name:
                continue  # don't evict the model we're trying to load
            model_size_gb = round(m.get("size", 0) / 1e9, 2)
            result = disp.unload_model(mname)
            if result and result.get("success"):
                freed_gb += model_size_gb
                log.info("model_dispatch: evicted %s (%.1fGB) to free RAM for %s", mname, model_size_gb, model_name)

        return (available_gb + freed_gb) >= needed_gb

    except Exception as exc:
        log.debug("model_dispatch: _ensure_ram_for_model failed: %s", exc)
        return False


#: The expiry statement, hoisted so tests can execute the REAL SQL rather than a
#: copy of it. A retyped duplicate in a test drifts from the code silently, and a
#: source-text assertion passes on the very comment describing the bug — both are
#: the "check that cannot fail" trap. Import this and run it.
_EXPIRE_STALE_SQL = """
    UPDATE dispatch_pending_queue
       SET status = 'expired',
           completed_at = NOW(),
           error = COALESCE(
               error,
               'expired: still queued at expires_at — no worker claimed it'
           )
     WHERE status = 'queued'
       AND expires_at IS NOT NULL
       AND expires_at < NOW()
"""


def _expire_stale_tasks() -> int:
    """Mark tasks past their expires_at as expired. Returns count."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            # Layer-3 (#269999): capture delegation rows about to expire FIRST so
            # we can notify their unified_tasks (else they orphan in_progress).
            cur.execute(
                """
                SELECT id FROM dispatch_pending_queue
                 WHERE status = 'queued'
                   AND expires_at IS NOT NULL
                   AND expires_at < NOW()
                   AND callback_type = 'delegation_result'
                """,
            )
            expiring_delegations = [r["id"] for r in cur.fetchall()]
            # Record WHY (#5374). This UPDATE wrote status='expired' with error
            # left NULL, and only rows with callback_type='delegation_result' got
            # any explanation at all (via _handle_failure_callback below) — so
            # everything else expired mute. 1,784 such rows accumulated, and
            # because a terminal status with no reason is indistinguishable from
            # a mystery, they were logged as the single largest "unmonitored
            # dispatch failure class" and investigated as one. They were not a
            # failure class: measured 2026-07-28, ALL 1,832 expired rows ever are
            # capability='warmup' — model warm-ups that sat queued past their
            # deadline. Real work has never once expired. One sentence here would
            # have made that legible from the row itself.
            #
            # COALESCE, not assignment: never clobber a real error already set by
            # whatever actually failed.
            cur.execute(_EXPIRE_STALE_SQL)
            rowcount = cur.rowcount
            for _qid in expiring_delegations:
                _handle_failure_callback(cur, _qid, "queue task expired before execution")

            # Warmup fallback TTL (#5699 item 3). kin_warmth rows carry a 12-min
            # expires_at, but any capability='warmup' row that lands WITHOUT one
            # would otherwise sit until the dept_hq 2h reaper shot it as
            # 'expired: no drain worker' — polluting the real-work failure bucket
            # (all 1,791 historic 'expired' rows were warmup noise). Keep warmup
            # strictly minutes-scale, labelled as what it is.
            cur.execute("SELECT value FROM platform_settings WHERE key='dispatch:warmup_ttl_min'")
            _wt = cur.fetchone()
            try:
                warmup_ttl = int(str(_wt["value"])) if _wt else WARMUP_TTL_MIN_DEFAULT
            except (ValueError, TypeError):
                warmup_ttl = WARMUP_TTL_MIN_DEFAULT
            warmup_ttl = max(warmup_ttl, 2)  # floor: never mass-expire live warmups
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                   SET status = 'expired',
                       completed_at = NOW(),
                       error = COALESCE(error, %s)
                 WHERE status = 'queued'
                   AND capability = 'warmup'
                   AND queued_at < NOW() - (%s * INTERVAL '1 minute')
                """,
                ("expired: warmup TTL (%dm) — infrastructure ping, not real work" % warmup_ttl, warmup_ttl),
            )
            warmup_expired = cur.rowcount
            if warmup_expired:
                log.debug("[MDW] expired %s warmup row(s) past the %sm fallback TTL", warmup_expired, warmup_ttl)
            rowcount += warmup_expired

            # Reap orphaned 'running' rows. A dead worker thread or a timed-out
            # completion barrier can leave a task 'running' forever — no other reaper
            # touches 'running', and _claim_tasks only claims 'queued'. Threshold sits
            # well above the ~240s max cold-load so live-but-slow tasks are never reaped.
            cur.execute("SELECT value FROM platform_settings WHERE key='dispatch:running_reap_secs'")
            _rr = cur.fetchone()
            try:
                reap_secs = int(str(_rr["value"])) if _rr else 900
            except (ValueError, TypeError):
                reap_secs = 900
            # Floor-clamp: a fat-fingered/negative/zero setting would make
            # make_interval(secs => 0) match every live 'running' row and mass-fail
            # active inference — the exact incident class this reaper prevents.
            reap_secs = max(reap_secs, 300)
            cur.execute(
                "UPDATE dispatch_pending_queue SET status='failed', error=%s, completed_at=NOW() "
                "WHERE status='running' AND claimed_at IS NOT NULL "
                "AND claimed_at < NOW() - make_interval(secs => %s)",
                ("reaped: stuck running > %ss" % reap_secs, reap_secs),
            )
            reaped = cur.rowcount
            if reaped:
                log.warning("[MDW] reaped %s orphaned 'running' task(s) (stuck > %ss)", reaped, reap_secs)
            return rowcount
    except Exception as exc:
        log.debug("model_dispatch: expire_stale_tasks failed: %s", exc)
        return 0


def _get_highest_priority_queued_model() -> Optional[str]:
    """Return the model_needed for the highest-priority waiting batch.

    Skips rows with invalid/sentinel model names ('none', 'None', '',
    'comfyui') — those are non-Ollama tasks that shouldn't have landed here
    in the first place (see department_dispatcher INSERT guard). Without
    this filter, the worker pings Ollama with a bogus name every cycle and
    the 404 spam blocks every other deferred draft (KB mistake_learned filed).
    """
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT model_needed, MAX(priority) AS max_prio, COUNT(*) AS cnt
                FROM dispatch_pending_queue
                WHERE status = 'queued'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND model_needed IS NOT NULL
                  AND lower(trim(model_needed)) NOT IN ('', 'none', 'null', 'comfyui')
                GROUP BY model_needed
                ORDER BY max_prio DESC, cnt DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            return row["model_needed"] if row else None
    except Exception as exc:
        log.debug("model_dispatch: get_highest_priority_queued_model failed: %s", exc)
        return None


# ── Main worker ──────────────────────────────────────────────────────────────


def model_dispatch_worker() -> None:
    """15-second APScheduler job — model-affinity queue drainer.

    Drains dispatch_pending_queue by routing tasks to whichever hub or
    fleet node has the required model already warm. Minimises VRAM swaps.

    Multi-node improvement (ADR-017): when the same model is warm on multiple
    nodes simultaneously, tasks are dispatched to ALL warm nodes in parallel
    via _CPU_EXECUTOR — one task per node per model per cycle. This prevents
    the old pattern where hub monopolised all work for a given model while
    outpost nodes with the same model sat idle.
    """
    start = time.time()
    total_executed = 0

    # #5699: claim only what the pool can actually START this cycle. Claiming a row
    # flips it to 'running'; a row claimed with no free thread rots until the 900s
    # reaper. Reserve PINNED_RESERVED_SLICE threads for the pinned (fleet-node)
    # drain so a sustained unpinned queue can't starve fleet warm-keeps (#3804).
    free_slots = _executor_free_slots()

    # 0. Keep fleet inventory honest before routing (throttled to 60s internally).
    #    Prevents routing into a node whose advertised models are stale (the
    #    Starship-246 wipe case) and auto-heals genuinely-missing models.
    try:
        reconcile_fleet_models()
    except Exception as exc:
        log.debug("model_dispatch: reconcile skipped: %s", exc)

    # 1. Expire stale tasks
    expired = _expire_stale_tasks()
    if expired:
        log.info("model_dispatch: expired %d stale task(s)", expired)

    # 2. Discover warm models across ALL nodes — {model: [node_id_or_None, ...]}
    all_warm_by_model = _get_all_warm_nodes_for_models()
    if all_warm_by_model:
        log.debug("model_dispatch: warm across fleet — %s", {m: len(nodes) for m, nodes in all_warm_by_model.items()})

    # 3. Drain queued tasks — dispatch to ALL warm nodes for each model in parallel.
    #    Each node gets its own claimed task batch (one claim per node so tasks don't
    #    duplicate). #5699: the cycle NO LONGER BLOCKS on a completion barrier — the
    #    old 300s as_completed() barriers stretched cycles to 5-12+ minutes and, with
    #    max_instances=1 + coalesce=True, silently skipped every 15s fire in between
    #    (926 skips/72h). Claims are bounded by FREE pool threads instead, so nothing
    #    is claimed that cannot start; double-claim is impossible because _claim_tasks
    #    only touches status='queued'. Results/errors surface via _on_task_done.
    unpinned_budget = _unpinned_budget(free_slots)
    # #6749: drain by queue pressure, never dict insertion order — see _drain_order.
    for model_name, node_ids in _drain_order(all_warm_by_model, _queue_head_age_by_model()):
        if total_executed >= unpinned_budget:
            break
        for node_id in node_ids:
            if total_executed >= unpinned_budget:
                break
            # Claim a batch of tasks for this model+node combination
            per_node_limit = min(MAX_TASKS_PER_MODEL, unpinned_budget - total_executed)
            tasks = _claim_tasks(model_name, limit=per_node_limit)
            for task in tasks:
                node_label = f"node:{node_id}" if node_id else "hub"
                log.debug("model_dispatch: submitting %s→%s to thread pool", model_name, node_label)
                _submit_task(task, node_id)
                total_executed += 1

    # 3.5 Drain tasks pinned to fleet nodes (cold-load acceptable). Pinned tasks run
    # on the pinned NODE's Ollama and are mostly cheap kin_warmth pings; the
    # PINNED_RESERVED_SLICE threads held back from the unpinned budget above
    # guarantee this drain a floor every cycle (#3804/#375). Bounded by what is
    # actually startable — an unstartable claim would rot as 'running' (#5699).
    _pinned_limit = min(4, free_slots - total_executed)
    if _pinned_limit > 0:
        preferred_tasks = _claim_preferred_node_tasks(limit=_pinned_limit)
        for task in preferred_tasks:
            _submit_task(task)
            total_executed += 1

    # 4. Cold-load the highest-priority queued model when it is warm NOWHERE.
    #    #5699: this was gated on `total_executed == 0`, but the constant kin_warmth
    #    pinned stream kept total_executed >= 1 nearly every cycle, so queued work
    #    needing a cold model (classify — the dominant expiry class, 945 rows/7d)
    #    starved until something else happened to warm it. Trigger on the actual
    #    condition instead: queued work exists for a model with no warm home.
    next_model = _get_highest_priority_queued_model()
    if next_model and not _model_is_warm(next_model, all_warm_by_model):
        log.info("model_dispatch: no warm node has %s — preparing to load it", next_model)
        try:
            # Clear RAM before attempting load — evict idle models if needed
            ram_ok = _ensure_ram_for_model(next_model)
            if not ram_ok:
                log.warning("model_dispatch: could not free enough RAM for %s — will retry", next_model)
            else:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                disp = get_dispatcher()
                readiness = disp.ensure_model_ready("model_dispatch_worker", next_model)
                if readiness and readiness.get("ready"):
                    log.info("model_dispatch: %s now ready, will drain on next cycle", next_model)
        except Exception as exc:
            log.debug("model_dispatch: model load request failed for %s: %s", next_model, exc)

    elapsed_ms = int((time.time() - start) * 1000)
    if total_executed > 0 or expired > 0:
        log.info(
            "model_dispatch: cycle done — executed=%d expired=%d elapsed=%dms",
            total_executed,
            expired,
            elapsed_ms,
        )

    # 5. Heartbeat — EVERY cycle, including idle ones (#5699 item 4). The worker
    #    previously wrote nothing to autonomy_loop_log and its cycle-done line only
    #    printed when executed>0, so a 50h whole-scheduler outage AND chronic
    #    10-minute cycles were both invisible in data. The liveness monitor
    #    (services/dispatch_drain_monitor.py) alarms when this heartbeat stops.
    _log_cycle_heartbeat(
        executed=total_executed,
        expired=expired,
        duration_ms=elapsed_ms,
        free_slots=free_slots,
        inflight=len(_INFLIGHT),
    )


def _log_cycle_heartbeat(executed: int, expired: int, duration_ms: int, free_slots: int, inflight: int) -> None:
    """Write one autonomy_loop_log row per worker cycle. Fail-open: never raises.

    autonomy_loop_log is pruned at 14 days by dispatch_retention_prune, so the
    15s cadence is bounded (~80k rows max). A broken heartbeat writer must never
    block the drain path — errors are logged at debug and swallowed.
    """
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO autonomy_loop_log
                    (job_name, status, items_processed, items_failed, duration_ms, details, department)
                VALUES ('model_dispatch_worker', 'success', %s, %s, %s, %s, 'Department HQ')
                """,
                (
                    executed,
                    expired,
                    duration_ms,
                    json.dumps({"free_slots": free_slots, "inflight": inflight}),
                ),
            )
    except Exception as exc:
        log.debug("model_dispatch: heartbeat write failed: %s", exc)
