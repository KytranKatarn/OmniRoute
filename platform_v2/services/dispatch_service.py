"""
Dispatch Service — executes LLM inference using an assigned agent's model.

Calls Ollama /api/generate with the assigned agent's model and host,
then releases the agent back to the coordinator in a finally block.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    success: bool = False
    response: str = ""
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DispatchService:
    def __init__(self, coordinator=None):
        if coordinator is None:
            from services.department_coordinator import get_coordinator

            coordinator = get_coordinator()
        self._coordinator = coordinator

    def dispatch(
        self,
        assignment,
        prompt: str,
        system_prompt: str = "",
        json_mode: bool = False,
        timeout: int = 120,
        job_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        POST a prompt to Ollama using the agent assigned in *assignment*.

        Always releases the agent in a finally block regardless of outcome.
        """
        result = DispatchResult(model_used=assignment.model)
        start_ms = int(time.time() * 1000)

        try:
            payload: dict = {
                "model": assignment.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_ctx": 4096,
                    "num_predict": 1024,
                },
            }

            if system_prompt:
                payload["system"] = system_prompt

            if json_mode:
                payload["format"] = "json"

            url = f"{assignment.host}/api/generate"
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

            result.response = data.get("response", "")
            result.completion_tokens = data.get("eval_count", 0)
            result.prompt_tokens = data.get("prompt_eval_count", 0)
            result.success = True

        except Exception as exc:
            error_str = str(exc)
            logger.error(
                "dispatch failed agent=%s model=%s: %s",
                assignment.agent_name,
                assignment.model,
                error_str,
            )
            # Normalise timeout error message for callers
            if "timed out" in error_str.lower() or "timeout" in error_str.lower():
                result.error = f"timed out: {error_str}"
            else:
                result.error = error_str

        finally:
            result.duration_ms = int(time.time() * 1000) - start_ms
            try:
                self._coordinator.release_agent(assignment.agent_id, job_id)
            except Exception as rel_exc:  # noqa: BLE001
                logger.error(
                    "release_agent failed for agent_id=%s: %s",
                    assignment.agent_id,
                    rel_exc,
                )

        return result

    # ------------------------------------------------------------------
    # DB helper
    # ------------------------------------------------------------------

    @staticmethod
    def _get_db_password() -> str:
        """Read DB password from Docker secret file, fall back to env var."""
        secret_file = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
        try:
            with open(secret_file) as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError):
            return os.environ.get("DB_PASSWORD", "")

    def _get_db(self):
        """Get a database connection for job operations."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=self._get_db_password(),
            cursor_factory=RealDictCursor,
        )

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def create_job(
        self,
        job_type: str,
        module_source: str,
        description: str,
        total_steps: int,
        capability: Optional[str] = None,
        metadata: Optional[dict] = None,
        agent_name: Optional[str] = None,
        station_code: Optional[str] = None,
    ) -> Optional[int]:
        """Create a bridge job with duplicate prevention.

        Uses advisory lock + duplicate check. Returns job_id or None.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            lock_key = hash(f"{job_type}:{module_source}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

            cur.execute(
                """SELECT id FROM bridge_jobs
                   WHERE job_type = %s AND module_source = %s AND status = 'running'
                   ORDER BY created_at DESC LIMIT 1""",
                (job_type, module_source),
            )
            existing = cur.fetchone()
            if existing:
                eid = existing["id"]
                conn.rollback()
                logger.info(
                    "dispatch_service: duplicate blocked %s/%s (job #%s)",
                    job_type,
                    module_source,
                    eid,
                )
                return None

            from psycopg2.extras import Json

            cur.execute(
                """INSERT INTO bridge_jobs
                   (job_type, module_source, description, total_steps,
                    status, agent_name, station_code, metadata, created_at)
                   VALUES (%s, %s, %s, %s, 'running', %s, %s, %s, NOW())
                   RETURNING id""",
                (
                    job_type,
                    module_source,
                    description,
                    total_steps,
                    agent_name,
                    station_code,
                    Json(metadata) if metadata else None,
                ),
            )
            job_id = cur.fetchone()["id"]
            conn.commit()
            logger.info(
                "dispatch_service: created job #%s (%s/%s)",
                job_id,
                job_type,
                module_source,
            )
            return job_id
        except Exception as exc:
            logger.error("dispatch_service: create_job failed: %s", exc)
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def update_job_progress(
        self,
        job_id: int,
        completed_delta: int = 0,
        failed_delta: int = 0,
    ) -> bool:
        """Increment job progress counters."""
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """UPDATE bridge_jobs
                   SET completed_steps = COALESCE(completed_steps, 0) + %s,
                       failed_steps = COALESCE(failed_steps, 0) + %s
                   WHERE id = %s""",
                (completed_delta, failed_delta, job_id),
            )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("dispatch_service: update_job_progress failed: %s", exc)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def complete_job(self, job_id: int, status: str = "auto") -> bool:
        """Mark a job as completed/failed/cancelled.

        If status='auto', determines from completed_steps and failed_steps.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            if status == "auto":
                cur.execute(
                    "SELECT completed_steps, failed_steps, total_steps FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row:
                    completed = row["completed_steps"] or 0
                    failed = row["failed_steps"] or 0
                    if completed == 0 and failed == 0:
                        status = "cancelled"
                    elif completed == 0 and failed > 0:
                        status = "failed"
                    else:
                        status = "completed"
                else:
                    status = "completed"

            cur.execute(
                "UPDATE bridge_jobs SET status = %s, completed_at = NOW() WHERE id = %s",
                (status, job_id),
            )
            conn.commit()
            logger.info("dispatch_service: job #%s -> %s", job_id, status)
            return True
        except Exception as exc:
            logger.error("dispatch_service: complete_job failed: %s", exc)
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_dispatch_service: Optional[DispatchService] = None
_lock_imported = False


def get_dispatch_service() -> DispatchService:
    global _dispatch_service
    if _dispatch_service is None:
        _dispatch_service = DispatchService()
    return _dispatch_service
