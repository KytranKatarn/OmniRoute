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
    "chat_capture": "skills.chat_capture",
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
            "chat_capture",
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
        # #4007: session-bound jobs honour the session's browse-from-country
        # egress preference (preference-not-pin — resolver returns None → hub).
        # params.egress_node is an explicit per-call override that wins.
        proxy_override = None
        if row["job_type"] in ("session_fetch", "authenticated_fetch") and params.get("agent_id"):
            from proxy_selector import resolve_session_egress

            plat = (params.get("platform") or "").lower()
            proxy_override = resolve_session_egress(
                int(params.get("agent_id") or 0), plat, params.get("egress_node")
            )
            if proxy_override:
                logger.info("Job #%d egress via session preference (proxy set)", job_id)
        # Generic per-job egress (ANY job_type) — params.egress = node_name | 'rotate'.
        # The skill-agnostic cluster-egress primitive: WTF/future jobs travel out through a
        # different node's IP for international reach + anti-flagging. Session jobs above
        # resolved their own egress; only fill in if still unset.
        if proxy_override is None:
            _choice = params.get("egress") or params.get("egress_node") or params.get("region")
            if _choice:
                from proxy_selector import resolve_egress_choice

                proxy_override = resolve_egress_choice(_choice)
                if proxy_override:
                    logger.info("Job #%d egress via choice=%r (proxy set)", job_id, _choice)
        slot_id, page = None, None
        t0 = time.time()
        ok = False
        try:
            slot_id, page = self.pool.claim(egress_tier=tier, proxy_override=proxy_override)
            skill_mod = importlib.import_module(module_path)
            result = skill_mod.run(
                page=page,
                url=row["target_url"],
                params=params,
                job_id=job_id,
            )
            self._complete(job_id, result, tier)
            ok = True
        except Exception:
            self._fail(job_id, traceback.format_exc())
        finally:
            if slot_id is not None and page is not None:
                self.pool.release(slot_id, page)
            try:
                self._log_telemetry(row, ok, int((time.time() - t0) * 1000), proxy_override)
            except Exception:
                logger.warning("telemetry log failed for job #%d", job_id)

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

    def _log_telemetry(self, row, success: bool, duration_ms: int, proxy_override) -> None:
        """Best-effort 0-token visibility row in task_execution_log so S.C.O.U.T.'s browser
        jobs show on the dispatch / Token Economy surface alongside LLM dispatch (#4228).

        Scraper jobs make NO model calls — tokens are genuinely 0; this does NOT alter LLM
        token accounting (every real model call stays DHQ-tracked). It surfaces the token-free
        browser work + which cluster node it egressed through, so the picture is complete.
        """
        from urllib.parse import urlparse

        host = ""
        try:
            host = urlparse(row.get("target_url") or "").netloc
        except Exception:
            pass
        meta = {
            "scout_job_id": row["id"],
            "egress": proxy_override or "hub",
            "target_host": host,
        }
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO task_execution_log
                         (agent_name, worker_type, task_type, capability, module_source,
                          request_origin, model_used, provider, prompt_tokens, completion_tokens,
                          tokens_used, cost, duration_ms, success, created_at, request_metadata)
                       VALUES ('S.C.O.U.T.', 'internal', %s, %s, 'scraper', %s, 'browser', 'local',
                               0, 0, 0, 0, %s, %s, NOW(), %s)""",
                    (
                        row["job_type"],
                        row["job_type"],
                        row.get("requested_by") or "scraper",
                        duration_ms,
                        success,
                        psycopg2.extras.Json(meta),
                    ),
                )
