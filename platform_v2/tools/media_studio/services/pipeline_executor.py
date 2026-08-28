"""Pipeline executor service — runs multi-step workflow templates as background jobs.

Each template step is executed sequentially; the result_id from one step is
passed as prev_result_id to the next, enabling chained generate→edit workflows.
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Any

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STEP_TIMEOUTS = {
    "generate": 600,
    "edit_inpaint": 300,
    "edit_outpaint": 300,
    "edit_upscale": 300,
    "edit_img2img": 300,
    "edit_style_transfer": 300,
    "batch": 1800,
}
POLL_INTERVAL = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_pipeline(
    template_id: int,
    overrides: Optional[Dict] = None,
    owner_type: str = "user",
    owner_id: int = 0,
) -> Dict:
    """Start a pipeline execution in the background.

    Args:
        template_id: ID of the workflow template to execute.
        overrides: dict keyed by step index (string "0", "1", …); values are
                   merged over the step's params before execution.
        owner_type: "user" or "project".
        owner_id: ID of the owning entity.

    Returns:
        {"execution_id": int, "status": "running"} or {"error": str}.
    """
    from tools.media_studio.services.template_service import get_template

    template = get_template(template_id)
    if not template:
        return {"error": f"Template {template_id} not found"}

    steps: List[Dict] = template.get("steps", [])
    if not steps:
        return {"error": "Template has no steps"}

    # Apply overrides
    if overrides:
        steps = [dict(s) for s in steps]  # shallow copy list
        for idx_str, override_params in overrides.items():
            try:
                idx = int(idx_str)
                if 0 <= idx < len(steps):
                    merged = dict(steps[idx].get("params", {}))
                    merged.update(override_params)
                    steps[idx] = dict(steps[idx])
                    steps[idx]["params"] = merged
            except (ValueError, TypeError):
                logger.warning("Pipeline override: invalid step index %s", idx_str)

    # INSERT execution record
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO media_pipeline_executions
                    (template_id, owner_type, owner_id, status, current_step,
                     total_steps, result_ids, created_at)
                VALUES (%s, %s, %s, 'running', 0, %s,
                        %s::jsonb, NOW())
                RETURNING id
                """,
                (
                    template_id,
                    owner_type,
                    owner_id,
                    len(steps),
                    psycopg2.extras.Json([]),
                ),
            )
            row = cur.fetchone()
            execution_id = row["id"]
    except Exception as exc:
        logger.error("Failed to create pipeline execution: %s", exc)
        return {"error": str(exc)}

    # Grab Flask app object before handing off to background thread
    from flask import current_app

    app = current_app._get_current_object()

    t = threading.Thread(
        target=_run_pipeline,
        args=(app, execution_id, steps, owner_type, owner_id),
        daemon=True,
    )
    t.start()

    return {"execution_id": execution_id, "status": "running"}


def get_pipeline_status(execution_id: int) -> Optional[Dict]:
    """Return the current state of a pipeline execution, or None if not found."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, template_id, owner_type, owner_id, status,
                       current_step, total_steps, result_ids, error_message,
                       failed_at_step, created_at, completed_at
                FROM media_pipeline_executions
                WHERE id = %s
                """,
                (execution_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    except Exception as exc:
        logger.error("get_pipeline_status error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


def _run_pipeline(
    app: Any,
    execution_id: int,
    steps: List[Dict],
    owner_type: str,
    owner_id: int,
) -> None:
    with app.app_context():
        result_ids: List[Any] = []
        prev_result_id = None
        i = 0
        try:
            for i, step in enumerate(steps):
                _update_execution(execution_id, current_step=i + 1)
                result = _execute_step(step, prev_result_id, owner_type, owner_id)
                if "error" in result:
                    _fail_execution(execution_id, result["error"], i + 1)
                    return
                prev_result_id = result.get("result_id")
                result_ids.append(prev_result_id)
                _update_execution(execution_id, result_ids=result_ids)
            _complete_execution(execution_id, result_ids)
        except Exception as exc:
            logger.exception("Pipeline %s crashed at step %d", execution_id, i + 1)
            _fail_execution(execution_id, str(exc), i + 1)


# ---------------------------------------------------------------------------
# Step router
# ---------------------------------------------------------------------------


def _execute_step(
    step: Dict,
    prev_result_id: Optional[int],
    owner_type: str,
    owner_id: int,
) -> Dict:
    step_type: str = step.get("step_type", "")

    # ---- generate -----------------------------------------------------------
    if step_type == "generate":
        from tools.media_studio.services.generation_service import submit_generation

        params = step.get("params", {})
        r = submit_generation(
            user_id=owner_id,
            media_type=params.get("media_type", "image"),
            prompt=params.get("prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            params=params,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        if "error" in r:
            return r
        queue_id = r["queue_id"]
        wait = _wait_for_completion("media_generation_queue", "id", queue_id, STEP_TIMEOUTS.get("generate", 600))
        if "error" in wait:
            return wait
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id FROM media_library WHERE metadata->>'queue_id' = %s ORDER BY id DESC LIMIT 1",
                (str(queue_id),),
            )
            row = cur.fetchone()
        if not row:
            return {"error": f"No media_library entry found for queue {queue_id}"}
        return {"result_id": row["id"]}

    # ---- edit_* -------------------------------------------------------------
    if step_type.startswith("edit_"):
        from tools.media_studio.services.edit_service import submit_edit

        edit_type = step_type.replace("edit_", "")
        params = step.get("params", {})
        r = submit_edit(
            source_id=prev_result_id,
            edit_type=edit_type,
            params=params,
            mask_data=None,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        if "error" in r:
            return r
        edit_id = r["edit_id"]
        # Lanczos upscale completes immediately
        if r.get("status") == "completed":
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT result_id FROM media_edits WHERE id = %s", (edit_id,))
                row = cur.fetchone()
            return {"result_id": row["result_id"]} if row else {"error": "Edit result not found"}
        wait = _wait_for_completion("media_edits", "id", edit_id, STEP_TIMEOUTS.get(step_type, 300))
        if "error" in wait:
            return wait
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT result_id FROM media_edits WHERE id = %s", (edit_id,))
            row = cur.fetchone()
        return {"result_id": row["result_id"]} if row and row["result_id"] else {"error": "Edit produced no result"}

    # ---- batch --------------------------------------------------------------
    if step_type == "batch":
        from tools.media_studio.services.batch_service import create_batch

        params = step.get("params", {})
        r = create_batch(
            name="pipeline_batch",
            owner_type=owner_type,
            owner_id=owner_id,
            media_type=params.get("media_type", "image"),
            prompts=params.get("prompts", []),
            base_params=params.get("base_params", {}),
        )
        if "error" in r:
            return r
        batch_id = r["batch_id"]
        wait = _wait_for_completion("media_batches", "id", batch_id, STEP_TIMEOUTS.get("batch", 1800))
        if "error" in wait:
            return wait
        return {"result_id": batch_id}

    return {"error": f"Unknown step_type: {step_type}"}


# ---------------------------------------------------------------------------
# Polling helper
# ---------------------------------------------------------------------------


def _wait_for_completion(table: str, id_col: str, id_val: int, timeout: int = 300) -> Dict:
    """Poll a table row until status is completed/failed or timeout expires."""
    # Guard against unexpected table names
    allowed_tables = {"media_generation_queue", "media_edits", "media_batches"}
    if table not in allowed_tables:
        return {"error": f"Unknown table: {table}"}

    elapsed = 0
    while elapsed < timeout:
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    f"SELECT status, error_message FROM {table} WHERE {id_col} = %s",
                    (id_val,),
                )
                row = cur.fetchone()
        except Exception as exc:
            return {"error": f"DB poll error: {exc}"}

        if not row:
            return {"error": f"Row not found in {table} where {id_col}={id_val}"}
        if row["status"] in ("completed", "complete"):
            return {"status": "completed"}
        if row["status"] == "failed":
            return {"error": row.get("error_message") or "Step failed"}
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return {"error": f"Timed out after {timeout}s waiting for {table} id={id_val}"}


# ---------------------------------------------------------------------------
# Execution state helpers
# ---------------------------------------------------------------------------


def _update_execution(
    execution_id: int,
    current_step: Optional[int] = None,
    result_ids: Optional[List] = None,
) -> None:
    sets = []
    values: List[Any] = []
    if current_step is not None:
        sets.append("current_step = %s")
        values.append(current_step)
    if result_ids is not None:
        sets.append("result_ids = %s")
        values.append(psycopg2.extras.Json(result_ids))
    if not sets:
        return
    values.append(execution_id)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                f"UPDATE media_pipeline_executions SET {', '.join(sets)} WHERE id = %s",
                values,
            )
    except Exception as exc:
        logger.error("_update_execution error: %s", exc)


def _complete_execution(execution_id: int, result_ids: List) -> None:
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_pipeline_executions
                SET status = 'completed',
                    result_ids = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (psycopg2.extras.Json(result_ids), execution_id),
            )
    except Exception as exc:
        logger.error("_complete_execution error: %s", exc)


def _fail_execution(execution_id: int, error_message: str, failed_at_step: int) -> None:
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_pipeline_executions
                SET status = 'failed',
                    error_message = %s,
                    failed_at_step = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (error_message, failed_at_step, execution_id),
            )
    except Exception as exc:
        logger.error("_fail_execution error: %s", exc)
