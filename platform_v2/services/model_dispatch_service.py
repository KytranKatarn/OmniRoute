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
                response = result.get("response", "")
                _mark_done(task_id, response, result.get("model", model), tokens, None)
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
            from tools.department_hq.services.department_dispatcher import dispatch

            # Step 1: R.O.S.E.T.T.A. translates to Québécois French
            qc_draft = ""
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

            # Step 2: combine and queue for Telegram approval
            if qc_draft:
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

            metadata = task.get("metadata") or {}
            approval_id = request_approval(
                action_type="linkedin_post",
                action_data={
                    "content": combined,
                    "hashtags": metadata.get("hashtags", []),
                    "post_type": task.get("requested_by", "personal").replace("S.I.G.N.A.L.", "personal"),
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
    #    clear RAM if needed then load the highest-priority model batch
    if total_executed == 0:
        next_model = _get_highest_priority_queued_model()
        if next_model:
            log.info("model_dispatch: no warm model matches queue — preparing to load %s", next_model)
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
