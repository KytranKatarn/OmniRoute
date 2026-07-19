"""Async job store for hire-name generation (#4969).

The DHQ Approvals "Generate" name button ran ``suggest_name`` SYNCHRONOUSLY
(6-23s, up to ~60s worst case), holding a gunicorn worker thread the whole time.
This backs an async flow: ``create_job`` inserts a ``generating`` row and spawns a
daemon thread that runs the (slow) sovereign-local identity build and persists the
result; the frontend polls ``get_job`` by ``job_id``.

State lives in the ``hire_name_jobs`` table (NOT an in-memory dict) because
archie_platform runs 4 gunicorn workers — an in-process store would let the POST
and the poll land on different workers. The daemon thread survives because a
gunicorn worker stays alive (unlike a one-shot ``python3 -c`` process, KB #270002).
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Callable, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

_JOB_TTL_MINUTES = 15


def _generate(hire_id: Optional[int], capability: str) -> dict[str, Any]:
    """Run the (slow) sovereign-local identity build. Isolated + mockable seam.

    ``_ensure_import_paths()`` FIRST: the dispatch path lazily imports ai_bridge,
    which raises ``ModuleNotFoundError: No module named 'db'`` without it (KB #272154).
    """
    from services.signal_calendar_service import _ensure_import_paths

    _ensure_import_paths()
    from services import agent_identity_builder

    return agent_identity_builder.build_identity(capability)


def _run_job(job_id: str, hire_id: Optional[int], capability: str) -> None:
    """Background worker: generate, then persist result/status. Never raises."""
    try:
        result = _generate(hire_id, capability)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE hire_name_jobs SET status='done', result=%s::jsonb, updated_at=now() WHERE job_id=%s",
                (json.dumps(result), job_id),
            )
    except Exception as e:  # a worker crash must not take down the process
        logger.warning("hire-name job %s failed: %s", job_id, e)
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "UPDATE hire_name_jobs SET status='error', error=%s, updated_at=now() WHERE job_id=%s",
                    (str(e)[:300], job_id),
                )
        except Exception:
            pass


def create_job(
    hire_id: Optional[int],
    capability: str,
    *,
    _runner: Optional[Callable[..., None]] = None,
) -> str:
    """Insert a ``generating`` job and spawn its background worker. Returns job_id.

    ``_runner`` is a test seam — inject a synchronous runner to avoid a real thread
    + real dispatch in unit tests.
    """
    job_id = str(uuid.uuid4())
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "INSERT INTO hire_name_jobs (job_id, hire_id, capability, status) " "VALUES (%s, %s, %s, 'generating')",
            (job_id, hire_id, capability),
        )
    prune_old()
    runner = _runner or _run_job
    threading.Thread(
        target=runner,
        args=(job_id, hire_id, capability),
        daemon=True,
        name=f"hirename-{job_id[:8]}",
    ).start()
    return job_id


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    """Return ``{status, result, error}`` for a job_id, or None if unknown."""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute("SELECT status, result, error FROM hire_name_jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return {"status": row["status"], "result": row["result"], "error": row["error"]}
    return {"status": row[0], "result": row[1], "error": row[2]}


def prune_old() -> None:
    """Best-effort delete of jobs older than the TTL. Never raises."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "DELETE FROM hire_name_jobs WHERE created_at < now() - make_interval(mins => %s)",
                (int(_JOB_TTL_MINUTES),),
            )
    except Exception as e:
        logger.debug("hire-name prune failed: %s", e)
