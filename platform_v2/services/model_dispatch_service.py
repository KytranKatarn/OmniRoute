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

import logging
import time
from typing import Optional

from database import get_db_cursor
from psycopg2.extras import RealDictCursor

log = logging.getLogger("platform.model_dispatch")

# Max tasks claimed per model per cycle — prevents one model monopolising a cycle
MAX_TASKS_PER_MODEL = 3
# Max total tasks per cycle across all models
MAX_TASKS_PER_CYCLE = 8


# ── Helpers ──────────────────────────────────────────────────────────────────


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
    """Return {model_name: node_id} for models warm on online fleet nodes.

    Reads the ollama_models JSONB column populated by the heartbeat.
    Falls back to checking metadata if ollama_models column not yet present.
    """
    result: dict[str, int] = {}
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id, hostname,
                       COALESCE(
                           (SELECT jsonb_agg(m->>'name')
                            FROM jsonb_array_elements(
                                COALESCE(metadata->'ollama_models', '[]'::jsonb)
                            ) AS m),
                           '[]'::jsonb
                       ) AS model_names
                FROM remote_nodes
                WHERE is_active = TRUE
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                  AND ollama_available = TRUE
                """
            )
            for row in cur.fetchall():
                models = row.get("model_names") or []
                if isinstance(models, list):
                    for name in models:
                        if name and name not in result:
                            result[name] = row["id"]
    except Exception as exc:
        log.debug("model_dispatch: node warm-model check failed: %s", exc)
    return result


def _claim_tasks(model_needed: str, limit: int = MAX_TASKS_PER_MODEL) -> list[dict]:
    """Atomically claim up to `limit` queued tasks for a given model."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                SET status = 'running', claimed_at = NOW()
                WHERE id IN (
                    SELECT id FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND model_needed = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY priority DESC, queued_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """,
                (model_needed, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        log.error("model_dispatch: claim_tasks failed for %s: %s", model_needed, exc)
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
    except Exception as exc:
        log.error("model_dispatch: mark_failed failed for task %d: %s", task_id, exc)


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
    except Exception as exc:
        log.debug("model_dispatch: callback failed for task %d: %s", task_id, exc)


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
        if node_id:
            # Route to fleet node
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            disp = get_dispatcher()
            result = disp._dispatch_to_node(
                agent_info={
                    "agent_name": task.get("agent_name", "unknown"),
                    "model": model,
                    "node_id": node_id,
                    "node_hostname": "",  # dispatcher resolves from DB
                    "node_name": "",
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
                _mark_done(task_id, result.get("response", ""), model, 0, node_id)
            else:
                _mark_failed(task_id, result.get("error", "node dispatch failed") if result else "no result")
        else:
            # Run on hub via dispatcher _execute_llm
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            disp = get_dispatcher()
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
                _mark_done(task_id, result.get("response", ""), result.get("model", model), tokens, None)
            else:
                error = result.get("error", "llm returned failure") if result else "no result"
                _mark_failed(task_id, error)

    except Exception as exc:
        log.error("model_dispatch: task #%d execution failed: %s", task_id, exc)
        _mark_failed(task_id, str(exc)[:500])


def _expire_stale_tasks() -> int:
    """Mark tasks past their expires_at as expired. Returns count."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE dispatch_pending_queue
                SET status = 'expired', completed_at = NOW()
                WHERE status = 'queued'
                  AND expires_at IS NOT NULL
                  AND expires_at < NOW()
                """,
            )
            return cur.rowcount
    except Exception as exc:
        log.debug("model_dispatch: expire_stale_tasks failed: %s", exc)
        return 0


def _get_highest_priority_queued_model() -> Optional[str]:
    """Return the model_needed for the highest-priority waiting batch."""
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT model_needed, MAX(priority) AS max_prio, COUNT(*) AS cnt
                FROM dispatch_pending_queue
                WHERE status = 'queued'
                  AND (expires_at IS NULL OR expires_at > NOW())
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
    """
    start = time.time()
    total_executed = 0

    # 1. Expire stale tasks
    expired = _expire_stale_tasks()
    if expired:
        log.info("model_dispatch: expired %d stale task(s)", expired)

    # 2. Discover warm models — hub first, then fleet nodes
    hub_warm = _get_warm_models_hub()
    node_warm = _get_warm_models_nodes()  # {model_name: node_id}
    all_warm = {**{m: None for m in hub_warm}, **node_warm}
    # Hub takes priority — if model is warm on both hub and node, hub wins
    for m in hub_warm:
        all_warm[m] = None

    if all_warm:
        log.debug("model_dispatch: warm models — hub: %s | nodes: %s", hub_warm, node_warm)

    # 3. Drain queued tasks for warm models
    for model_name, node_id in all_warm.items():
        if total_executed >= MAX_TASKS_PER_CYCLE:
            break
        remaining = min(MAX_TASKS_PER_MODEL, MAX_TASKS_PER_CYCLE - total_executed)
        tasks = _claim_tasks(model_name, limit=remaining)
        for task in tasks:
            _execute_task(task, node_id=node_id)
            total_executed += 1

    # 4. If capacity remaining and nothing was warm for the queue,
    #    load the highest-priority model batch
    if total_executed == 0:
        next_model = _get_highest_priority_queued_model()
        if next_model:
            log.info("model_dispatch: no warm model matches queue — requesting load of %s", next_model)
            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                disp = get_dispatcher()
                readiness = disp.ensure_model_ready("model_dispatch_worker", next_model)
                if readiness and readiness.get("ready"):
                    # Model loaded — drain on the next cycle (15s)
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
