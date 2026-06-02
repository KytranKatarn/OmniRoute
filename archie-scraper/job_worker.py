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
    # Core data collection
    "web_scrape": "skills.web_scrape",
    "multi_page_scrape": "skills.multi_page_scrape",
    "authenticated_fetch": "skills.authenticated_fetch",
    "session_fetch": "skills.session_fetch",
    "search_scrape": "skills.search_scrape",
    "site_change_monitor": "skills.site_change_monitor",
    "pdf_extract": "skills.pdf_extract",
    "document_download": "skills.document_download",
    # Client UX intelligence
    "ux_audit": "skills.ux_audit",
    "login_test": "skills.login_test",
    "signup_flow": "skills.signup_flow",
    "network_inspect": "skills.network_inspect",
    "accessibility_check": "skills.accessibility_check",
    "seo_snapshot": "skills.seo_snapshot",
    "broken_link_check": "skills.broken_link_check",
    "screenshot_diff": "skills.screenshot_diff",
    "form_audit": "skills.form_audit",
    "competitor_snapshot": "skills.competitor_snapshot",
    # Domain-specific
    "procurement_sync": "skills.procurement_sync",
    "ancestry_research": "skills.ancestry_research",
    "crm_enrich": "skills.crm_enrich",
    "contact_harvest": "skills.contact_harvest",
    "social_profile_check": "skills.social_profile_check",
    "price_monitor": "skills.price_monitor",
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
        auto_approve = job_type in {
            "web_scrape", "multi_page_scrape", "authenticated_fetch", "session_fetch",
            "search_scrape", "site_change_monitor", "pdf_extract",
            "document_download", "procurement_sync", "ancestry_research",
            "crm_enrich", "contact_harvest", "social_profile_check", "price_monitor",
        }
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
