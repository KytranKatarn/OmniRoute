import importlib
import json
import logging
import threading
import time
import traceback

import psycopg2.extras

from database import get_db
from proxy_selector import select_egress

logger = logging.getLogger(__name__)

SKILL_MAP = {
    "web_scrape": "skills.web_scrape",
    "ux_audit": "skills.ux_audit",
    "procurement_sync": "skills.procurement_sync",
}
_POLL_INTERVAL = 5


class JobWorker:
    def __init__(self, pool):
        self.pool = pool
        self._running = False

    def start(self) -> None:
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="scout-worker")
        t.start()
        logger.info("JobWorker started, polling every %ds", _POLL_INTERVAL)

    def enqueue(
        self,
        job_type: str,
        target_url: str,
        params: dict,
        egress_tier: int,
        requested_by: str,
    ) -> int:
        auto_approve = job_type in ("web_scrape", "procurement_sync")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO scout_jobs
                       (job_type, target_url, params, egress_tier,
                        requested_by, status, auto_approve)
                       VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                       RETURNING id""",
                    (
                        job_type,
                        target_url,
                        json.dumps(params),
                        egress_tier,
                        requested_by,
                        auto_approve,
                    ),
                )
                return cur.fetchone()["id"]

    def _loop(self) -> None:
        while self._running:
            try:
                self._process_next()
            except Exception:
                logger.exception("JobWorker loop error")
            time.sleep(_POLL_INTERVAL)

    def _process_next(self) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = 'running', started_at = NOW()
                       WHERE id = (
                           SELECT id FROM scout_jobs
                           WHERE status = 'pending'
                           ORDER BY created_at ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, job_type, target_url, params,
                                 egress_tier, requested_by""",
                )
                row = cur.fetchone()
        if not row:
            return

        job_id = row["id"]
        logger.info("Processing job #%d type=%s", job_id, row["job_type"])

        module_path = SKILL_MAP.get(row["job_type"])
        if not module_path:
            self._fail(job_id, f"Unknown job_type: {row['job_type']!r}")
            return

        params = (
            row["params"]
            if isinstance(row["params"], dict)
            else json.loads(row["params"] or "{}")
        )
        tier = select_egress(row["target_url"], row["egress_tier"])
        slot_id, page = None, None
        try:
            slot_id, page = self.pool.claim(egress_tier=tier)
            skill_mod = importlib.import_module(module_path)
            result = skill_mod.run(
                page=page,
                url=row["target_url"],
                params=params,
                job_id=job_id,
            )
            self._complete(job_id, result, tier)
        except Exception:
            self._fail(job_id, traceback.format_exc())
        finally:
            if slot_id is not None and page is not None:
                self.pool.release(slot_id, page)

    def _complete(self, job_id: int, result: dict, egress_tier: int) -> None:
        status = "approved" if result.get("auto_approve") else "needs_review"
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = %s, completed_at = NOW(), egress_tier = %s,
                           data = %s, screenshots = %s,
                           network_log = %s, findings = %s
                       WHERE id = %s""",
                    (
                        status,
                        egress_tier,
                        psycopg2.extras.Json(result.get("data")),
                        psycopg2.extras.Json(result.get("screenshots", [])),
                        psycopg2.extras.Json(result.get("network_log", [])),
                        result.get("findings", ""),
                        job_id,
                    ),
                )
        logger.info("Job #%d completed → %s", job_id, status)

    def _fail(self, job_id: int, error: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scout_jobs
                       SET status = 'failed', completed_at = NOW(),
                           error_log = %s
                       WHERE id = %s""",
                    (error[:4000], job_id),
                )
        logger.error("Job #%d failed", job_id)
