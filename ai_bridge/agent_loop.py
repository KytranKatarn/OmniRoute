"""
Agent Loop — The Heartbeat of ARCHIE's Proactive Autonomy

Attaches to the existing APScheduler BackgroundScheduler and processes:
- Email queue (pending outbound emails)
- Scheduled tasks (due tasks from get_due_scheduled_tasks())
- Reminders (due reminders from get_due_reminders())
- Approval queue (auto-approve tier-1, expire stale tier-2, execute approved)

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from db import get_db

# Allow importing platform_v2 services from ai_bridge context
if "/mnt/archie_brain/platform_v2" not in sys.path:
    sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from services.time_utils import now_local_str
from services.agent_service import (
    recover_idle,
)

logger = logging.getLogger("agent_loop")


def log_governance_event(event_type, action, outcome, details=None, event_category="system", agent_id=None):
    """Log a governance event to the immutable audit log"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, action, outcome, details, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (event_type, event_category, agent_id, action, outcome, json.dumps(details or {})),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log governance event: {e}")


def _send_approval_telegram(approval_id: int, action_type: str, action_data: dict, reason: str):
    """Route an approval request through the director_reports inbox.

    The triage consumer detects category='approval_request' and escalates
    immediately with Approve/Deny/Defer inline keyboard markup.
    """
    import sys as _sys
    import os as _os

    platform_path = _os.path.join(_os.path.dirname(__file__), "..", "platform_v2")
    if platform_path not in _sys.path:
        _sys.path.insert(0, platform_path)
    try:
        from services.director_report_service import submit_via_inbox

        import re as _re

        def _strip_md(text):
            """Remove Markdown that breaks Telegram V1 parser."""
            text = _re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=_re.DOTALL)
            text = _re.sub(r"__(.+?)__", r"\1", text, flags=_re.DOTALL)
            return text

        lines = [f"Approval #{approval_id} required for: {action_type}"]
        if reason:
            lines.append(f"Reason: {_strip_md(reason)}")
        if action_data and action_type == "linkedin_post":
            post_type = action_data.get("post_type", "")
            hashtags = action_data.get("hashtags", [])
            if post_type:
                lines.append(f"Type: {post_type}")
            if hashtags:
                lines.append("Tags: " + " ".join(f"#{h}" for h in hashtags))
        elif action_data and action_type == "linkedin_like":
            lines.append(f"React: {action_data.get('reaction', 'like')}")
            if action_data.get("post_url"):
                lines.append(f"Post: {action_data['post_url']}")
        elif action_data and action_type == "linkedin_comment":
            if action_data.get("comment"):
                lines.append(f"Comment: {_strip_md(action_data['comment'])[:300]}")
            if action_data.get("post_url"):
                lines.append(f"Post: {action_data['post_url']}")
        elif action_data:
            for k, v in list(action_data.items())[:3]:
                lines.append(f"{k}: {v}")

        # Fast-path (#4757): media_hub (M.A.V.E.N.) approvals are interactive \u2014 the
        # owner is usually waiting on the request, so the ~30s triage-consumer poll
        # + inbox roundtrip is felt. Send the Approve/Deny Telegram INLINE here.
        # FAIL-SAFE: only skip the inbox when the inline send actually lands (a
        # message_id comes back); on ANY problem we fall through to submit_via_inbox
        # below, so delivery is never lost (worst case == the existing path). Scoped
        # to media_hub_action only \u2014 every other approval type is unchanged.
        if action_type == "media_hub_action":
            try:
                from services import telegram_service as _tg

                _res = _tg.send(
                    category="approval_request",
                    # Keep "#<id>" in the title \u2014 telegram_service.send parses it to
                    # build the esc_approve_{id}/esc_deny_{id} callback buttons.
                    title=f"[MEDIUM] Approval Required \u2014 {action_type} #{approval_id}",
                    message="\n".join(lines),
                    source_agent="A.R.C.H.I.E.",
                    force=True,
                    _privileged=True,
                    # voice=False = fast string template, NOT the LLM personality
                    # engine. This runs inline in the /api/internal/approval-request
                    # request path, and the M.A.V.E.N. caller times out at 8s — the
                    # LLM formatter can take ~8s and blow that budget (leaving the
                    # standalone thinking the approval failed while it actually
                    # succeeded). Same rationale as the Mail HQ new-mail advisory.
                    voice=False,
                )
                _mid = _res.get("message_id") if isinstance(_res, dict) else None
                if _mid:
                    try:
                        from database import get_db_cursor

                        with get_db_cursor(commit=True) as (_c2, _cur2):
                            _cur2.execute(
                                "UPDATE autonomy_approval_queue " "SET telegram_message_id = %s WHERE id = %s",
                                (_mid, approval_id),
                            )
                    except Exception as _mid_err:
                        logger.warning(
                            "approval #%s: inline message_id persist failed: %s",
                            approval_id,
                            _mid_err,
                        )
                    logger.info(
                        "Approval #%s sent inline to Telegram (media_hub fast-path)",
                        approval_id,
                    )
                    return  # delivered \u2014 do NOT also submit to the inbox (no double-send)
                logger.warning(
                    "approval #%s inline send returned no message_id \u2014 falling back to inbox",
                    approval_id,
                )
            except Exception as _inline_err:
                logger.warning(
                    "approval #%s inline Telegram send failed (%s) \u2014 falling back to inbox",
                    approval_id,
                    _inline_err,
                    exc_info=True,
                )

        submit_via_inbox(
            category="approval_request",
            title=f"Approval Required \u2014 {action_type} #{approval_id}",
            message="\n".join(lines),
            source_agent="A.R.C.H.I.E.",
            # An approval_request is a routine pending-approval (LinkedIn post, cloud
            # escalation, …), NOT a system incident — so it must NOT hold the cockpit
            # header in the red `critical` alert state. 'medium' still surfaces it in the
            # notification bell but does not flash the elbow red; genuine incidents stay
            # 'critical'. Approvals are actioned via Telegram + the Approvals queue.
            severity="medium",
            department="Executive Office",
        )
        logger.info(
            "Approval #%s submitted to director_reports inbox (category=approval_request)",
            approval_id,
        )
    except Exception as exc:
        logger.error("Failed to submit approval #%s to inbox: %s", approval_id, exc)


def _validate_approval_request(action_type: str, action_data: dict) -> Optional[str]:
    """Validate approval request inputs. Returns error message or None if valid."""
    if not action_type or not isinstance(action_type, str):
        return "action_type must be a non-empty string"
    if not isinstance(action_data, dict):
        return "action_data must be a dict"
    return None


def tab_merge_refusal(summary: str, verdict_ok: bool, gate_ok: bool, gate_reason: str) -> "str | None":
    """Why the Approvals tab must NOT merge this PR — or None if it may (#5834).

    Pure, so the decision table is testable without a DB, GitHub or a Flask app.

    The tab merges with ``human_override=True``, which bypasses
    ``_automerge_governance_ok`` entirely. That is CORRECT for the ALLOWLIST — a
    sensitive path deliberately requires a human and the tap IS that human — but
    it must not also excuse a STALE VERDICT. Decision #953: safety properties are
    universal, authority limits are per-actor. Nobody, owner included, can review
    a commit that did not exist when they were asked.

    Only staleness (and a missing/negative verdict) refuses here. An allowlist or
    tier refusal is precisely what the human tap clears, so it must NOT block.
    """
    if not summary:
        return "no stored F.O.R.G.E. review — a dead review is not an approval"
    if not verdict_ok:
        return "the stored verdict is NOT an approval — re-review before merging"
    low = str(gate_reason or "").lower()
    if not gate_ok and (("stale verdict" in low) or ("head is now" in low)):
        return f"STALE VERDICT — {gate_reason}"
    return None


def _check_existing_approval(action_type: str, action_data: dict, cur) -> bool:
    """Check if a pending approval that would collide with this request already exists.

    Dedup key depends on the action_type:

      - ``contractor_dispatch`` uses ``(action_type, agent, capability)`` so
        two parallel contractor runs for different agents / capabilities
        can be in flight at the same time without blocking each other.
        Phase 7 smoke testing discovered that a coarse action_type-only
        dedup was blocking every new contractor approval whenever one
        was already pending. Fall back to the coarse check if the JSON
        fields are missing so we never bypass dedup entirely.

      - ``linkedin_post`` dedups on ``(action_type, content)`` so distinct
        posts (e.g. an EN and an FR launch announcement, or posts for
        different accounts) can await approval simultaneously, while the
        same text can never be queued twice (#3944).

      - All other action_types keep the original coarse check — one
        pending approval per action_type at a time.
    """
    if action_type == "linkedin_post":
        content = (action_data or {}).get("content")
        if content:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'content' = %s
                LIMIT 1
                """,
                (action_type, content),
            )
            return cur.fetchone() is not None

    if action_type == "pr_merge":
        # #5829: pr_merge dedups on (action_type, pr_number). The coarse
        # action_type-only check meant ONLY ONE PR could await approval at a
        # time — every other escalation was silently dropped while one sat
        # pending, and `_mark_kytran_approval_sent()` still recorded it as
        # asked, so it was never raised again.
        #
        # Measured 2026-08-19: 108 PRs flagged kytran_approval_sent, only 78
        # ever got a row. Concretely, while PR #2703's approval sat pending
        # 19:32-22:41, the escalations for #2697/#2705/#2706 (21:11) and
        # #2700/#2707 (21:41) all evaporated. They stayed open, believed
        # escalated, and never appeared in the Approvals tab — whose own
        # subtitle promises "Approve here or via Telegram — same result".
        #
        # This is the THIRD time this exact trap has been fixed: the docstring
        # above records it for contractor_dispatch (Phase 7 smoke testing) and
        # for linkedin_post (#3944). A coarse per-action_type dedup is only
        # correct when the action is genuinely a singleton; a merge approval
        # never was.
        pr_no = (action_data or {}).get("pr_number")
        if pr_no is not None:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'pr_number' = %s
                LIMIT 1
                """,
                (action_type, str(pr_no)),
            )
            return cur.fetchone() is not None
        # No pr_number in the payload -> fall through to the coarse check rather
        # than bypass dedup entirely (same fallback rule as contractor_dispatch).

    if action_type in ("linkedin_like", "linkedin_comment", "linkedin_comment_like"):
        # Engagement actions dedup on (action_type, post_urn, acting browser agent) —
        # multi-account engagement (Terry 377 + Kytran 342) means approvals for
        # DIFFERENT posts/accounts must be able to await approval simultaneously
        # (the same coarse-dedup trap #3944 fixed for linkedin_post). The same
        # post+agent+action can still never queue twice.
        urn = (action_data or {}).get("post_urn")
        aid = str((action_data or {}).get("browser_agent_id") or "")
        if urn:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'post_urn' = %s
                  AND COALESCE(action_data->>'browser_agent_id','') = %s
                LIMIT 1
                """,
                (action_type, urn, aid),
            )
            return cur.fetchone() is not None

    if action_type == "deploy_approve":
        # Dedup on (action_type, proposal_id) — the same trap #3944 fixed for linkedin_post
        # and Phase 7 fixed for contractor_dispatch. Under the coarse check only ONE deploy
        # approval could be pending at a time, so the self-heal backlog drained at 1 per
        # 3h cycle: 108 verified fixes would have taken ~13.5 days, and approval_max was
        # silently meaningless (2 of every 3 were deduped away and counted as failures).
        # Distinct proposals are independent decisions and must be able to await approval
        # together; the SAME proposal still can never queue twice. Each one remains
        # human-tapped and still runs the sandbox gate + W.A.R.D.E.N. clearance before
        # anything deploys, so concurrency here costs no safety.
        pid = (action_data or {}).get("proposal_id")
        if pid:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'proposal_id' = %s
                LIMIT 1
                """,
                (action_type, str(pid)),
            )
            return cur.fetchone() is not None

    if action_type == "contractor_dispatch":
        agent = (action_data or {}).get("agent")
        capability = (action_data or {}).get("capability")
        if agent:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > NOW())
                  AND action_data->>'agent' = %s
                  AND (action_data->>'capability') IS NOT DISTINCT FROM %s
                LIMIT 1
                """,
                (action_type, agent, capability),
            )
            return cur.fetchone() is not None

    if action_type == "website_deploy":
        # Dedup per DOMAIN so different domains can await approval at once,
        # while the same domain can't queue twice (#4344 follow-up).
        domain = (action_data or {}).get("domain")
        if domain:
            cur.execute(
                "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "AND action_data->>'domain' = %s LIMIT 1",
                (action_type, domain),
            )
            return cur.fetchone() is not None

    if action_type == "model_rightsizing":
        # Dedup per AGENT so every agent's swap can await approval at once, while the same
        # agent can't queue two pending swaps in one nightly run (P2-C part 2, #381).
        rs_agent = (action_data or {}).get("agent_id")
        if rs_agent is not None:
            cur.execute(
                "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "AND action_data->>'agent_id' = %s LIMIT 1",
                (action_type, str(rs_agent)),
            )
            return cur.fetchone() is not None

    if action_type == "improvement_approve_red":
        # Red Code-Health findings card the OWNER for permission at proposal
        # time (owner order 2026-07-11): distinct red proposals must be able to
        # await approval simultaneously, while the same proposal can never
        # queue twice (same per-item pattern as linkedin_post / #3944).
        pid = (action_data or {}).get("proposal_id")
        if pid is not None:
            cur.execute(
                "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' "
                "AND (expires_at IS NULL OR expires_at > NOW()) "
                "AND action_data->>'proposal_id' = %s LIMIT 1",
                (action_type, str(pid)),
            )
            return cur.fetchone() is not None

    cur.execute(
        "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' "
        "AND (expires_at IS NULL OR expires_at > NOW()) LIMIT 1",
        (action_type,),
    )
    return cur.fetchone() is not None


def _get_effective_tier(action_type: str, tier: int, cur) -> int:
    """Determine effective tier by checking tier-1 auto-approve config."""
    cur.execute("SELECT config_value FROM autonomy_config WHERE config_key = 'tier1_auto_approve'")
    row = cur.fetchone()
    tier1_types = row["config_value"].get("types", []) if row else []
    return 1 if action_type in tier1_types else tier


# A RECURRING producer must never be blocked by its own previous, unactioned
# request. The default 24h window exactly matches a daily job's period, so the
# new run races the old row's expiry: on 2026-07-28 the 03:00 website deploy
# filed 11 SECONDS before the 07-27 pair expired, dedup swallowed both domains,
# the old pair then expired, and the site went a full day with no approval and
# no deploy — silently (task #5359). Give recurring producers a window SHORTER
# than their period so yesterday's request is always expired by the time the
# next one is filed. Everything unlisted keeps the 24h default.
_APPROVAL_EXPIRY_HOURS = {
    "website_deploy": 20,  # daily 03:00 producer → 20h < 24h period
}


def _create_approval_record(
    action_type: str,
    action_data: dict,
    reason: str,
    requested_by: str,
    priority: int,
    effective_tier: int,
    cur,
) -> int:
    """Insert approval record into the DB. Returns the new approval_queue ID."""
    status = "approved" if effective_tier == 1 else "pending"
    expiry_hours = int(_APPROVAL_EXPIRY_HOURS.get(action_type, 24))

    cur.execute(
        f"""
        INSERT INTO autonomy_approval_queue
        (action_type, action_data, tier, status, priority, requested_by, reason,
         approved_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s,
                {'NOW()' if effective_tier == 1 else 'NULL'},
                NOW() + INTERVAL '{expiry_hours} hours')
        RETURNING id
        """,
        (
            action_type,
            json.dumps(action_data),
            effective_tier,
            status,
            priority,
            requested_by,
            reason,
        ),
    )
    return cur.fetchone()["id"]


def request_approval(
    action_type: str,
    action_data: dict,
    reason: str,
    requested_by: str = "agent_loop",
    priority: int = 5,
    tier: int = 2,
) -> Optional[int]:
    """
    Submit an action to the approval queue.

    Tier 1 actions are auto-approved immediately.
    Tier 2 actions wait for human approval.

    Returns the approval_queue ID, or None on failure.
    """
    try:
        # Validate inputs
        validation_error = _validate_approval_request(action_type, action_data)
        if validation_error:
            logger.error(f"Approval request validation failed: {validation_error}")
            return None

        # Skip cloud escalation for 0% ping jobs — these are orphaned fleet
        # dispatch handshakes left over from platform restarts, not real capacity
        # issues. Sending Telegram for every restart generates noise spam.
        if action_type == "cloud_throughput_escalation":
            busy = action_data.get("busy_job", {})
            if busy.get("progress_pct", -1) == 0 and "ping" in busy.get("description", "").lower():
                logger.info(
                    "[request_approval] Dropping cloud escalation — orphaned ping job: %s",
                    busy.get("description", "")[:80],
                )
                return None

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Determine effective tier
        effective_tier = _get_effective_tier(action_type, tier, cur)

        # Dedup: skip if there's already a pending approval that would collide.
        # For contractor_dispatch, collision is keyed on (agent, capability)
        # so parallel contractors/capabilities don't block each other.
        if effective_tier > 1 and _check_existing_approval(action_type, action_data, cur):
            logger.info(f"Skipping duplicate {action_type} — pending approval already exists")
            cur.close()
            conn.close()
            return None

        # Create the approval record
        approval_id = _create_approval_record(
            action_type, action_data, reason, requested_by, priority, effective_tier, cur
        )
        conn.commit()
        cur.close()
        conn.close()

        if effective_tier == 1:
            logger.info(f"Tier-1 auto-approved: {action_type} (#{approval_id})")
        else:
            logger.info(f"Tier-2 awaiting approval: {action_type} (#{approval_id})")
            # Push Telegram notification with Approve/Deny/Defer buttons
            _send_approval_telegram(approval_id, action_type, action_data, reason)

        return approval_id
    except Exception as e:
        logger.error(f"Failed to request approval: {e}")
        return None


# Maps agent loop job names to their owning department
JOB_DEPARTMENT_MAP = {
    "fleet_health_check": "Operations & Infrastructure",
    "model_state_save": "Operations & Infrastructure",
    "heartbeat_monitor": "Operations & Infrastructure",
    "automated_module_audit": "Engineering & Technology",
    "pattern_compliance_check": "Engineering & Technology",
    "proactive_scan": "Engineering & Technology",
    "compliance_scan": "Security & Compliance",
    "ethics_monitoring": "Security & Compliance",
    "knowledge_dedup": "Research & Development",
    "conversation_indexing": "Research & Development",
    "consciousness_analysis": "Research & Development",
    "embedding_batch": "Research & Development",
    "git_commit_tracking": "Research & Development",
    "github_skill_analysis": "Documentation & Knowledge",
    "skill_sync": "Documentation & Knowledge",
    "daily_code_health_digest": "Marketing & Communications",
    "welfare_recovery": "Human Resources & Culture",
    "training_tick": "Human Resources & Culture",
    "approval_queue": "Executive Office",
    "department_metrics_rollup": "Analytics & Intelligence",
    # Migrated from consciousness_scheduler (APScheduler in app.py)
    "conversation_consolidation": "Research & Development",
    "improvement_detection": "Engineering & Technology",
    "daily_self_reflection": "Executive Office",
    "weekly_memory_consolidation": "Research & Development",
    # Migrated from infrastructure scheduler (APScheduler in app.py)
    "batch_medium_issues": "Engineering & Technology",
    "auto_log_ingestion": "Research & Development",
    "weekly_dependency_scan": "Security & Compliance",
    "health_probe": "Operations & Infrastructure",
    "vps_health": "Operations & Infrastructure",
    "hub_containers_health": "Operations & Infrastructure",
    "translation_coverage_scan": "Documentation & Knowledge",
    "crew_wellness_tick": "Human Resources & Culture",
    "ollama_model_health": "Operations & Infrastructure",
    "media_queue_cleanup": "Creative & Design",
    "media_export_cleanup": "Creative & Design",
    "market_watch_cycle": "Analytics & Intelligence",
    "creed_accounting_audit": "Finance & Accounting",
}


class AgentLoop:
    """
    Proactive agent loop that processes queues on a schedule.

    Attaches jobs to the existing APScheduler BackgroundScheduler instance
    from init_consciousness_scheduler().
    """

    def __init__(self, scheduler, flask_app):
        self.scheduler = scheduler
        self.flask_app = flask_app
        self._running = False
        self._last_down_set: frozenset = frozenset()
        self._last_dns_class: str = "healthy"  # vigil_dns_monitor dedup (#4571)

    def _send_telegram(self, message, title="🔔 A.R.C.H.I.E."):
        """Send a Telegram alert as A.R.C.H.I.E. (thin wrapper over telegram_service.send_info).

        Restores the helper assumed by 8 monitor jobs (Stalwart queue, dependency-CVE,
        DNS-failure, KIN digest, network alerts, ...). It was never defined, so those
        alerts silently failed via their surrounding try/except.
        """
        from services.telegram_service import send_info

        return send_info(title, message)

    def start(self):
        """Attach agent loop jobs to the scheduler."""
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        # Startup recovery: reset any 'generating' jobs back to 'pending'.
        # If the platform restarted mid-generation, the ComfyUI polling thread
        # was killed and the job is stuck. Reset so P.I.X.E.L. re-queues on next tick.
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE media_generation_queue SET status='pending', started_at=NULL,
                       error_message='Reset on startup — platform restarted mid-generation'
                       WHERE status IN ('generating', 'dispatched')"""
                )
                if cur.rowcount:
                    logger.info("startup recovery: reset %d stuck 'generating' jobs to 'pending'", cur.rowcount)
        except Exception as e:
            logger.warning("startup recovery: could not reset generating jobs: %s", e)

        flask_app = self.flask_app

        def with_app_context(fn):
            """Wrap a function to run inside Flask app context."""

            def wrapper():
                with flask_app.app_context():
                    fn()

            wrapper.__name__ = fn.__name__
            return wrapper

        self.scheduler.add_job(
            with_app_context(self._process_email_queue),
            trigger=IntervalTrigger(seconds=60),
            id="agent_email_queue",
            name="Agent Loop: Email Queue",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._keep_embeddings_warm),
            trigger=IntervalTrigger(minutes=25),
            id="agent_embedding_keepwarm",
            name="Agent Loop: Embedding Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # #4270: keep the interactive cockpit conversation model (A.R.C.H.I.E.'s
        # qwen2.5:7b) CPU-warm on the hub so cockpit chat never cold-loads. Every
        # 30 min, shorter than the 45m keep_alive. Narrow, owner-approved
        # exception to the 7B-no-warmup policy (CPU-only → zero VRAM).
        self.scheduler.add_job(
            with_app_context(self._keep_cockpit_model_warm),
            trigger=IntervalTrigger(minutes=30),
            id="agent_cockpit_model_keepwarm",
            name="Agent Loop: Cockpit Model Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # F.O.R.G.E. review-model keep-warm (2026-06-23): keep qwen2.5:7b GPU-resident on the
        # Defiant review node so F.O.R.G.E. reviews don't cold-load → the 280-322s spikes that blew
        # the 240s per-node cap. Every 4 min (< any per-request keep_alive reset) with a 10m
        # keep_alive, online-gated. Toggle via id=forge_review_model_keepwarm.
        self.scheduler.add_job(
            with_app_context(self._keep_forge_review_model_warm),
            trigger=IntervalTrigger(minutes=4),
            id="forge_review_model_keepwarm",
            name="Agent Loop: F.O.R.G.E. Review Model Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Win 1 (2026-06-23): generalized keep-warm for the hot HUB 7Bs (qwen2.5:7b / mistral:7b /
        # qwen25-classify) — kills the 30-56s cold-load tax on ~24k dispatches/wk. CPU-pinned, every
        # 4 min. Toggle via id=cluster_model_keepwarm.
        self.scheduler.add_job(
            with_app_context(self._keep_cluster_models_warm),
            trigger=IntervalTrigger(minutes=4),
            id="cluster_model_keepwarm",
            name="Agent Loop: Cluster Hot-Model Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Win 2 (2026-06-23): keep the documentation model (mistral:7b) warm on Citadel (CPU async
        # worker) so the `documentation` dispatches now routed there hit it warm. Online-gated, every
        # 4 min. Toggle via id=citadel_async_model_keepwarm.
        self.scheduler.add_job(
            with_app_context(self._keep_citadel_async_model_warm),
            trigger=IntervalTrigger(minutes=4),
            id="citadel_async_model_keepwarm",
            name="Agent Loop: Citadel Async Model Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Cockpit fast-front keep-warm (2026-07-12): keep the cockpit's conversational model
        # (COCKPIT_CHAT_MODEL, llama3.2:3b) resident on the Defiant GPU node so A.R.C.H.I.E.'s
        # FIRST reply never cold-loads (the 14-34s variance the owner saw after PR #2217 routed
        # cockpit chat there). The deepen follow-up's 7B is already warmed by
        # forge_review_model_keepwarm on the same node, so this warms ONLY the small fast-front
        # model — no second 7B runner, no 8GB-VRAM crowding. CPU-pinned (matches the dispatch's
        # runner on the full-GPU node) + online-gated, every 4 min / 30m keep_alive. Toggle via
        # id=cockpit_node_model_keepwarm.
        self.scheduler.add_job(
            with_app_context(self._keep_cockpit_node_model_warm),
            trigger=IntervalTrigger(minutes=4),
            id="cockpit_node_model_keepwarm",
            name="Agent Loop: Cockpit Node Model Keep-Warm",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # ST-4 observer (2026-06-23): alert if F.O.R.G.E. review quality silently regresses — a guard
        # flag turned off, or the structured(json) ratio crashing. Every 6h, 12h alert cooldown.
        self.scheduler.add_job(
            with_app_context(self._forge_review_path_observer),
            trigger=IntervalTrigger(hours=6),
            id="forge_review_path_observer",
            name="Agent Loop: F.O.R.G.E. Review-Path Observer",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # #4035: outbound-mail delivery-failure monitor — alerts on Stalwart
        # queue messages failing delivery (high retry / aged / failed) or backlog.
        self.scheduler.add_job(
            with_app_context(self._stalwart_queue_monitor),
            trigger=IntervalTrigger(minutes=30),
            id="stalwart_queue_monitor",
            name="Agent Loop: Stalwart Outbound Queue Monitor",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # P2-PRODUCER (#381): nightly off-peak benchmark cycle (03:30 ET) — generates correctness-
        # graded data for right-sizing. Gated by platform_settings benchmark_producer_enabled
        # (default OFF); the job fires but no-ops until the flag is turned on.
        self.scheduler.add_job(
            with_app_context(self._run_benchmark_producer),
            trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
            id="benchmark_producer_cycle",
            name="Agent Loop: Benchmark Producer (P2-PRODUCER)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # P2-C part 2 (#381): nightly model right-sizing proposer (04:15 ET) — turns correctness-
        # graded proposals into Tier-2 approvals for the owner. No-op until graded data exists;
        # NEVER auto-applies (Tier-2 = owner approves each swap via Telegram).
        self.scheduler.add_job(
            with_app_context(self._run_model_rightsizing_proposer),
            trigger=CronTrigger(hour=4, minute=15, timezone="America/Toronto"),
            id="model_rightsizing_proposer",
            name="Agent Loop: P2-C Model Right-Sizing Proposer",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_scheduled_tasks),
            trigger=IntervalTrigger(seconds=30),
            id="agent_scheduled_tasks",
            name="Agent Loop: Scheduled Tasks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_reminders),
            trigger=IntervalTrigger(seconds=30),
            id="agent_reminders",
            name="Agent Loop: Reminders",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_approval_queue),
            trigger=IntervalTrigger(seconds=60),
            id="agent_approvals",
            name="Agent Loop: Approval Queue",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )

        # Approval-queue WEDGE watchdog (observer-first). The 60s executor job
        # above runs max_instances=1 — a single hung item wedges it for HOURS
        # while every tick logs "max instances reached" (live case 2026-07-02:
        # owner-approved #1832/#1833 frozen all morning until a restart). The
        # watchdog checks the SYMPTOM (approved rows sitting unexecuted) straight
        # from the DB, so it fires regardless of why execution stalled.
        self.scheduler.add_job(
            with_app_context(self._approval_queue_watchdog),
            trigger=IntervalTrigger(minutes=10),
            id="approval_queue_watchdog",
            name="Agent Loop: Approval Queue Watchdog",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )

        # S.I.G.N.A.L. calendar daily release (#3990) — due scheduled posts →
        # linkedin_post approval queue (Telegram gate). Slots are 09:00 ET, so
        # release at 09:05 ET; wide misfire grace drains 1/account next run.
        self.scheduler.add_job(
            with_app_context(self._signal_calendar_release),
            trigger=CronTrigger(hour=9, minute=5, timezone="America/Toronto"),
            id="signal_calendar_release",
            name="S.I.G.N.A.L.: Calendar Daily Release",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # S.I.G.N.A.L. calendar top-up (#3991) — when an account's scheduled
        # backlog thins below 3 posts, generate ONE fresh post via dispatch
        # and append it to the calendar. Runs after the morning release.
        self.scheduler.add_job(
            with_app_context(self._signal_calendar_topup),
            trigger=CronTrigger(hour=10, minute=0, timezone="America/Toronto"),
            id="signal_calendar_topup",
            name="S.I.G.N.A.L.: Calendar Generation Top-Up",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # A.R.C.H.I.E. Building Machine autonomous scheduler (#380, ADR-008).
        # HOURLY, asks archie_engine to pull in-scope platform issues from the Repair Bay
        # queue and build GATED PRs vs archie-platform (engine never merges; engine PRs are
        # auto-merge-gated). Live kill switch via work_control ("engine_autopull_cycle").
        #
        # WAS: IntervalTrigger(hours=6) + 1 issue/cycle. That was calibrated for a pipeline
        # with NO verification — "F.O.R.G.E. 7B fixes still need human triage". Lifetime
        # output under it: 8 PRs. The 2026-07-20 guards changed the premise: #5003 re-asserts
        # the finding before a PR is opened, #5009 blocks ungrounded approvals, #5004 skips
        # findings that no longer reproduce. Verification is what makes throughput safe, so
        # keeping the old rate paid the safety cost twice.
        #
        # CronTrigger, NOT IntervalTrigger, is deliberate: an interval job counts from
        # REGISTRATION, so every archie_scheduler restart silently pushed the next run a full
        # 6h out (it restarted 16x on 2026-07-20 alone — only 2 cycles fired in 24h instead
        # of 4). Cron fires on wall-clock and is restart-proof. timezone= is mandatory per
        # .claude/rules/timezone.md.
        self.scheduler.add_job(
            with_app_context(self._engine_autopull_cycle),
            trigger=CronTrigger(minute=17, timezone="America/Toronto"),
            id="engine_autopull_cycle",
            name="A.R.C.H.I.E. Building Machine: Auto-Pull Repair Work",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # Browser profile keep-warm (#3982) — daily READ through each
        # established device-trust profile so sessions don't go stale.
        self.scheduler.add_job(
            with_app_context(self._browser_profile_keepwarm),
            trigger=CronTrigger(hour=12, minute=30, timezone="America/Toronto"),
            id="browser_profile_keepwarm",
            name="S.C.O.U.T.: Browser Profile Keep-Warm",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # Cookie-session health probe (#3708 phase 2) — every 4h, READ-probe
        # each active cookie session; stale ones flip status so skills stop
        # trusting expired cookies. Persistent profiles use keep-warm instead.
        self.scheduler.add_job(
            with_app_context(self._browser_session_health_probe),
            trigger=IntervalTrigger(hours=4),
            id="browser_session_health_probe",
            name="S.C.O.U.T.: Cookie Session Health Probe",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # S.I.G.N.A.L. comment pipeline (#3992) — poll watched post threads
        # (READ) then draft replies for new comments (Tier-2 Telegram gate).
        self.scheduler.add_job(
            with_app_context(self._signal_comment_pipeline),
            trigger=IntervalTrigger(hours=6),
            id="signal_comment_pipeline",
            name="S.I.G.N.A.L.: Comment Monitor + Reply Drafts",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # S.I.G.N.A.L. engagement monitor (Phase 2) — scan the feed → PROPOSE
        # approval-gated likes/comments (Tier-2 Telegram). OFF by default; enable
        # via work_control 'signal_engagement_monitor'.
        self.scheduler.add_job(
            with_app_context(self._signal_engagement_monitor),
            trigger=IntervalTrigger(hours=8),
            id="signal_engagement_monitor",
            name="S.I.G.N.A.L.: Engagement Monitor (likes/comments proposals)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # S7-P1-4b: daily reset of every agent's engagement budget + abandon stale ledger
        # orphans (always safe / idempotent — runs even when the monitor is OFF).
        self.scheduler.add_job(
            with_app_context(self._reset_engagement_budgets),
            trigger=CronTrigger(hour=0, minute=5, timezone="America/Toronto"),
            id="reset_engagement_budgets",
            name="S.I.G.N.A.L.: Reset daily engagement budgets",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._archie_coo_approval_worker),
            trigger=IntervalTrigger(seconds=90),
            id="archie_coo_approvals",
            name="Agent Loop: A.R.C.H.I.E. COO Approval Worker",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # DISABLED 2026-04-14: 25 fails/day, old email integration — see Project #261
        # self.scheduler.add_job(
        #     with_app_context(self._check_email_inbox),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_email_inbox",
        #     name="Agent Loop: Email Inbox Check",
        #     replace_existing=True,
        # )

        # DISABLED 2026-04-14: depends on email_inbox above — see Project #261
        # self.scheduler.add_job(
        #     with_app_context(self._auto_analyze_emails),
        #     trigger=IntervalTrigger(minutes=10),
        #     id="agent_email_analyze",
        #     name="Agent Loop: Auto-Analyze Emails",
        #     replace_existing=True,
        # )

        self.scheduler.add_job(
            with_app_context(self._run_resolve_oversight),
            trigger=IntervalTrigger(minutes=30),
            id="resolve_email_oversight",
            name="Agent Loop: R.E.S.O.L.V.E. Email Oversight",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Email Memory Vault — Phase 1 (Project #377). All three workers are gated
        # behind the work-control flag 'memory_vault' (DEFAULT OFF) and no-op until
        # the owner enables it from the Autonomy tab — so they register safely but
        # do nothing until the Gmail accounts are re-authed + the flag is flipped.
        try:
            from tools.google_work_suite.services.memory_vault import (
                gmail_full_ingest_crawler,
                gmail_profile_extract_worker,
                gmail_profile_progress_observer,
                gmail_profile_synthesis_worker,
                gmail_profile_triage_worker,
                profile_embed_worker,
            )

            self.scheduler.add_job(
                with_app_context(gmail_full_ingest_crawler),
                trigger=IntervalTrigger(hours=6),
                id="memory_vault_crawler",
                name="Agent Loop: Memory Vault — Gmail Ingest Crawler",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                with_app_context(gmail_profile_triage_worker),
                trigger=IntervalTrigger(minutes=3),
                id="memory_vault_triage",
                name="Agent Loop: Memory Vault — Triage Worker",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                with_app_context(gmail_profile_extract_worker),
                trigger=IntervalTrigger(minutes=5),
                id="memory_vault_extract",
                name="Agent Loop: Memory Vault — Phase 2 Extract Worker",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                with_app_context(gmail_profile_progress_observer),
                trigger=IntervalTrigger(minutes=30),
                id="memory_vault_observer",
                name="Agent Loop: Memory Vault — Progress Observer",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                with_app_context(gmail_profile_synthesis_worker),
                trigger=CronTrigger(hour=2, minute=30, timezone="America/Toronto"),
                id="memory_vault_synthesis",
                name="Agent Loop: Memory Vault — Phase 2.2 Profile Synthesis",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                with_app_context(profile_embed_worker),
                trigger=IntervalTrigger(minutes=15),
                id="memory_vault_embed",
                name="Agent Loop: Memory Vault — Phase 2.4 Embeddings",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _mv_err:
            logger.warning("Memory Vault workers not scheduled: %s", _mv_err)

        self.scheduler.add_job(
            with_app_context(self._forward_notifications_to_telegram),
            trigger=IntervalTrigger(seconds=15),
            id="agent_telegram_notify",
            name="Agent Loop: Telegram Notifications",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_browser_tasks),
            trigger=IntervalTrigger(minutes=5),
            id="agent_browser_tasks",
            name="Agent Loop: Browser Tasks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._generate_briefings),
            trigger=IntervalTrigger(minutes=5),
            id="agent_briefings",
            name="Agent Loop: Briefings",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_anomalies),
            trigger=IntervalTrigger(minutes=5),
            id="agent_anomaly_detection",
            name="Agent Loop: Anomaly Detection",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # FIX8 (DR remediation): fleet-identity watchdog. Alerts on mass-offline or
        # duplicate-identity rows — the re-registration-storm signatures that ran
        # SILENT for ~13h on 2026-06-04. Alert-only; toggle: work key
        # 'fleet_identity_monitor'. See .claude/dr-postmortem-and-remediation.md.
        try:
            from services.fleet_identity_monitor import check_fleet_identity

            self.scheduler.add_job(
                with_app_context(check_fleet_identity),
                trigger=IntervalTrigger(minutes=5),
                id="fleet_identity_monitor",
                name="Agent Loop: Fleet Identity Monitor (FIX8)",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _fim_err:
            logger.warning("Fleet identity monitor not scheduled: %s", _fim_err)

        # Task #4031 (DR posture): warm-standby watchdog. Alerts when the
        # boston-2 replica slot is missing/inactive (the promoted-fork signature
        # that ran SILENT for 7 days, 06-04→06-11), WAL accumulates, replay
        # lags, or the nightly DR cold backup goes stale. Alert-only; toggle:
        # work key 'dr_posture_monitor'. KB #272169/#272172, ADR-006 (#726).
        try:
            from services.dr_posture_monitor import check_dr_posture

            self.scheduler.add_job(
                with_app_context(check_dr_posture),
                trigger=IntervalTrigger(minutes=15),
                id="dr_posture_monitor",
                name="Agent Loop: DR Posture Monitor (#4031)",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _drp_err:
            logger.warning("DR posture monitor not scheduled: %s", _drp_err)

        # PRIMARY backup posture (#5014). Sibling of the DR monitor above — DR freshness
        # was watched, but the tier we actually restore from was NOT. Full backups had been
        # OOM-killed for an unknown period and the restore point aged past 12h in silence.
        # The job meant to catch it queried a non-existent table and swallowed the error.
        # Same 15-min cadence as DR: alert LATENCY is what matters here, not volume — the
        # send_system cooldowns (12h stale / 6h failures) bound how often it can speak.
        # Alert-only, never mutates. KB #282926.
        try:
            from services.backup_posture_monitor import check_backup_posture

            self.scheduler.add_job(
                with_app_context(check_backup_posture),
                trigger=IntervalTrigger(minutes=15),
                id="backup_posture_monitor",
                name="Agent Loop: Backup Posture Monitor (#5014)",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _bpm_err:
            logger.warning("Backup posture monitor not scheduled: %s", _bpm_err)

        # Dispatch drain liveness (#5699). The queue's single consumer went absent
        # twice in one week — a 50h whole-scheduler outage and chronic 5-12 min
        # cycles under max_instances=1 — and 1,589 rows of real work were reaped as
        # 'expired: no drain worker' with nothing paging. Deterministic, no LLM:
        # watches the worker's per-cycle autonomy_loop_log heartbeat + queued
        # non-warmup rows aging with no claim progress. Alert-only, never mutates;
        # fail-open (a broken monitor must never block dispatch). 5-min cadence.
        try:
            from services.dispatch_drain_monitor import check_drain_liveness

            self.scheduler.add_job(
                with_app_context(check_drain_liveness),
                trigger=IntervalTrigger(minutes=5),
                id="dispatch_drain_liveness",
                name="Agent Loop: Dispatch Drain Liveness Monitor (#5699)",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _ddl_err:
            logger.warning("Dispatch drain liveness monitor not scheduled: %s", _ddl_err)

        # Dispatch posture (#5596). When both hub GPUs fell off the bus on
        # 2026-08-04 the platform ran at 2x latency / 10x failure rate / half
        # throughput for EIGHT DAYS and nothing paged — get_quick_summary kept
        # answering "Platform: OK" because it asks whether components ANSWER,
        # never whether they answer WELL. This compares a recent window against
        # the platform's own trailing baseline, so it is symptom-based: it also
        # catches node loss, a bad model pin, or a cause nobody has thought of.
        # Deterministic, no LLM in the alert path (an alarm that needs inference
        # cannot report that inference is broken). Alert-only, never mutates;
        # send_system cooldowns bound how often it can speak.
        try:
            from services.dispatch_posture_monitor import check_dispatch_posture

            self.scheduler.add_job(
                with_app_context(check_dispatch_posture),
                trigger=IntervalTrigger(minutes=15),
                id="dispatch_posture_monitor",
                name="Agent Loop: Dispatch Posture Monitor (#5596)",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
        except Exception as _dpm_err:
            logger.warning("Dispatch posture monitor not scheduled: %s", _dpm_err)

        self.scheduler.add_job(
            with_app_context(self._generate_reports),
            trigger=IntervalTrigger(minutes=15),
            id="agent_reports",
            name="Agent Loop: Scheduled Reports",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._notify_email_telegram),
            trigger=IntervalTrigger(seconds=30),
            id="agent_email_telegram_notify",
            name="Agent Loop: Email Telegram Notifications",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._track_agent_hr),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_hr_tracker",
        #     name="Agent Loop: HR Tracker",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._run_ethics_monitoring),
        #     trigger=IntervalTrigger(minutes=15),
        #     id="agent_ethics_monitoring",
        #     name="Agent Loop: Ethics Monitoring",
        #     replace_existing=True,
        # )

        self.scheduler.add_job(
            with_app_context(self._reap_stale_jobs),
            trigger=IntervalTrigger(minutes=2),
            id="agent_stale_job_reaper",
            name="Agent Loop: Stale Job Reaper",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._reap_stuck_jobs),
            trigger=IntervalTrigger(minutes=5),
            id="agent_stuck_job_watchdog",
            name="Agent Loop: Stuck Job Watchdog",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._platform_watchdog),
            trigger=IntervalTrigger(minutes=2),
            id="platform_watchdog",
            name="Agent Loop: Platform Watchdog (load/mem/swap)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Path C: scheduler sidecar heartbeat. HTTP routes that previously
        # read `current_app.config["AGENT_LOOP"].running` now read
        # scheduler_heartbeat instead, since the scheduler can live in a
        # different container than gunicorn.
        self.scheduler.add_job(
            with_app_context(self._write_scheduler_heartbeat),
            trigger=IntervalTrigger(seconds=30),
            id="scheduler_heartbeat",
            name="Agent Loop: Scheduler Heartbeat (30s)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._comfyui_idle_stop),
            trigger=IntervalTrigger(minutes=5),
            id="comfyui_idle_stop",
            name="Agent Loop: ComfyUI Idle Stop (30min)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_qa_scheduled),
            trigger=IntervalTrigger(hours=6),
            id="qa_scheduled_run",
            name="Agent Loop: P.R.O.B.E. QA Scheduled Run",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._process_training_tick),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_training_tick",
        #     name="Agent Loop: Training Progression Tick",
        #     replace_existing=True,
        # )

        # W.A.R.D.E.N. — admin ops autonomous jobs
        self.scheduler.add_job(
            with_app_context(self._run_warden_user_audit),
            trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
            id="warden_user_audit",
            name="W.A.R.D.E.N.: Daily User Account Audit",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_warden_backup_verify),
            trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
            id="warden_backup_verify",
            name="W.A.R.D.E.N.: Daily Backup Integrity Check",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_warden_compliance_check),
            # 10:00 ET (not 06:00): 06:00 is exactly when WARDEN's stationed LAN GPU
            # node (Starship-246) exits its 20:00–06:00 hardware-rest window with cold
            # models, so the dispatch queued + zombied. 10:00 = node fully awake (#4151).
            trigger=CronTrigger(day_of_week="sun", hour=10, minute=0, timezone="America/Toronto"),
            id="warden_compliance_check",
            name="W.A.R.D.E.N.: Weekly Admin Compliance Scan",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_warden_wtf_rsync),
            trigger=IntervalTrigger(minutes=15),
            id="warden_wtf_rsync",
            name="W.A.R.D.E.N.: WTF Code Sync Hub→VPS",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_proactive_scan),
            trigger=IntervalTrigger(hours=6),
            id="agent_proactive_scan",
            name="Agent Loop: Proactive Code Scan",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_dependency_audit),
            trigger=IntervalTrigger(hours=6, start_date="2026-01-01 03:30:00"),
            id="dependency_audit",
            name="Agent Loop: Dependency CVE Audit",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # S.P.E.C.T.R.A. — nightly dispatch misroute audit (Project #272 / Task #2105).
        # 02:15 UTC offset from the other nightly maintenance windows.
        self.scheduler.add_job(
            with_app_context(self._run_misroute_audit),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 02:15:00"),
            id="spectra_misroute_audit",
            name="Agent Loop: S.P.E.C.T.R.A. Dispatch Misroute Audit",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # S.P.E.C.T.R.A. → Audit Pipeline adapter (Project #272 / Task #2186).
        # 02:30 UTC — 15 min after the audit, so findings are fresh.
        self.scheduler.add_job(
            with_app_context(self._run_misroute_to_proposal_adapter),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 02:30:00"),
            id="misroute_to_proposal_adapter",
            name="Agent Loop: S.P.E.C.T.R.A. Misroute → Proposal Adapter",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # C.R.E.E.D. accounting self-audit — "use our own tools" (net-new).
        # Asserts the token/welfare/carbon accounting invariants daily and
        # alerts (never fixes) on drift. 06:30 ET — after the nightly
        # maintenance windows above, ahead of the business day.
        self.scheduler.add_job(
            with_app_context(self._run_creed_accounting_audit),
            trigger=CronTrigger(hour=6, minute=30, timezone="America/Toronto"),
            id="creed_accounting_audit",
            name="Agent Loop: C.R.E.E.D. Accounting Self-Audit",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Archie-as-delegate worker (Project #276 / Task #2209).
        # Polls unified_tasks for pending delegated work every 30s.
        # Fast cadence so Claude → Archie feels interactive, not batch.
        self.scheduler.add_job(
            with_app_context(self._run_delegate_task_worker),
            trigger=IntervalTrigger(seconds=30),
            id="delegate_task_worker",
            name="Agent Loop: Archie Delegate Task Worker",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # #4350: daily auto-triage of STALE blocked documentation delegations —
        # clear ones whose PR is already documented in the KB, re-queue
        # undocumented ones once. Stops the blocked backlog accumulating as
        # confusing 'docs skipped' clutter in the DHQ Dispatch view.
        self.scheduler.add_job(
            with_app_context(self._run_delegation_triage),
            trigger=CronTrigger(hour=5, minute=40, timezone="America/Toronto"),
            id="delegation_triage",
            name="Agent Loop: Stale Blocked-Delegation Triage (#4350)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Fleet Backlog Runner (Phase 3, #676) — DEFAULT OFF; promotes a few
        # pending unified_tasks to the fleet each cycle when enabled in the
        # Autonomy tab. Bounded so it never floods the cluster.
        self.scheduler.add_job(
            with_app_context(self._run_fleet_backlog_runner),
            trigger=IntervalTrigger(seconds=60),
            id="fleet_backlog_runner",
            name="Agent Loop: Fleet Backlog Runner",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Node auto-provision (#3732) — stocks a newly enrolled fleet node's
        # recommended warm-set automatically (idempotent diff vs present models →
        # OTA mesh_sync_log pull queue). DEFAULT OFF, gated by platform_settings
        # 'node_auto_provision_enabled'. Rate-limited (max 2 nodes/cycle).
        self.scheduler.add_job(
            with_app_context(self._run_node_auto_provision),
            trigger=IntervalTrigger(minutes=10),
            id="node_auto_provision",
            name="Agent Loop: Node Auto-Provision (warm-set)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Agent KB write auto-review (#3534 Phase 3). C.O.D.E.X. promotes/rejects
        # quarantined agent_proposed KB writes. Hourly; a no-op unless the
        # agentic_tool_write flag is on AND pending writes exist.
        self.scheduler.add_job(
            with_app_context(self._run_agent_kb_review),
            trigger=IntervalTrigger(hours=1),
            id="agent_kb_review",
            name="Agent Loop: Agent KB Write Auto-Review (C.O.D.E.X.)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # A.R.C.H.I.E. triage consumer — classifies director_reports every 30s,
        # escalates to Telegram only when warranted (Unified Voice Wave 2).
        self.scheduler.add_job(
            with_app_context(self._run_triage_consumer),
            trigger=IntervalTrigger(seconds=30),
            id="archie_triage_consumer",
            name="Agent Loop: A.R.C.H.I.E. Triage Consumer",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # K.I.N. — daily crew welfare + budget digest (Project #272 / Task #2106).
        # 02:45 UTC — after S.P.E.C.T.R.A. so routing anomalies are fresh.
        self.scheduler.add_job(
            with_app_context(self._run_kin_welfare_digest),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 02:45:00"),
            id="kin_welfare_digest",
            name="Agent Loop: K.I.N. Welfare + Budget Digest",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # E.T.H.O.S. — weekly ethics brief (task #3277). Reviews K.I.N.'s agent
        # welfare digest + the week's governance_audit_log and drafts an ethics
        # assessment. Sundays 05:30 ET — after the nightly digests, weekly cadence.
        self.scheduler.add_job(
            with_app_context(self._run_ethos_ethics_brief),
            trigger=CronTrigger(day_of_week="sun", hour=5, minute=30, timezone="America/Toronto"),
            id="ethos_ethics_brief",
            name="Agent Loop: E.T.H.O.S. Weekly Ethics Brief",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # E.T.H.O.S. — daily C.R.E.E.D. grant deadline reminders (task #3612).
        # 06:00 ET. Dormant until grants have deadlines within 7 days.
        self.scheduler.add_job(
            with_app_context(self._run_creed_grant_deadline_reminder),
            trigger=CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
            id="creed_grant_deadline_reminder",
            name="Agent Loop: C.R.E.E.D. Grant Deadline Reminder",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # F.O.R.G.E. — daily dep drift audit (Project #272 Phase 2 / Task #2109).
        # 03:15 UTC — after S.P.E.C.T.R.A. and K.I.N. digest windows.
        self.scheduler.add_job(
            with_app_context(self._run_dep_drift_audit),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 03:15:00"),
            id="forge_dep_drift",
            name="Agent Loop: F.O.R.G.E. Dependency Drift Audit",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Fleet capacity report — recommends node upgrades when sustained high load
        # (#2516 / ADR-555). 03:45 UTC after dep_drift window. Pure read job, no
        # mutations to fleet state.
        self.scheduler.add_job(
            with_app_context(self._run_fleet_capacity_report),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 03:45:00"),
            id="fleet_capacity_report",
            name="Agent Loop: Fleet Capacity Report",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # P.R.O.B.E. — daily agent-briefing health check (mistake #269358).
        # 04:15 UTC. Runs every chat briefing; flags any returning a swallowed
        # error (schema drift) instead of live module state, so the silent
        # briefing-breakage class (PRs #1301-1303) can't recur undetected.
        self.scheduler.add_job(
            with_app_context(self._run_briefing_health),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 04:15:00"),
            id="probe_briefing_health",
            name="Agent Loop: P.R.O.B.E. Briefing Health Check",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # F.O.R.G.E. — PR review polling (Project #247 Phase 1 / Task #1799).
        # Polls GitHub every 5 min for new/changed open PRs; upserts pr_reviews.
        self.scheduler.add_job(
            with_app_context(self._run_pr_review_poll),
            trigger=IntervalTrigger(minutes=5),
            id="forge_pr_review_poll",
            name="Agent Loop: F.O.R.G.E. PR Review Polling",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # F.O.R.G.E. AI diff analysis — processes up to 3 pending PR reviews every 3 min.
        # Was 10 min. The PR pipeline is three POLL-DRIVEN stages in series —
        # poll (5) → review (10) → tier/merge (10) — so an approved Tier-2 PR
        # could wait ~28 min on timers alone and the owner reliably beat the
        # machinery to it by hand (measured 2026-07-28: every PR that day was
        # Tier 2, i.e. A.R.C.H.I.E.'s to merge, and every one was merged
        # manually first). This job only calls GitHub when a PR is actually
        # pending review, so a shorter tick is near-free: idle ticks are one DB
        # query. Rate headroom at the time of the change: 4994/5000.
        self.scheduler.add_job(
            with_app_context(self._run_pr_diff_analysis),
            trigger=IntervalTrigger(minutes=3),
            id="forge_pr_diff_analysis",
            name="Agent Loop: F.O.R.G.E. PR Diff Analysis",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # F.O.R.G.E. review durability net (#4583): recover PR reviews stuck 'in_progress'
        # (an on-demand review_pr() that died with its CLI) → reset to pending + re-drive
        # server-side, so review lifetime no longer depends on any caller process staying alive.
        self.scheduler.add_job(
            with_app_context(self._run_review_reaper),
            trigger=IntervalTrigger(minutes=5),
            id="forge_review_reaper",
            name="Agent Loop: F.O.R.G.E. Stuck-Review Reaper",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Email IMAP sync is owned solely by JobService (jobsvc_email_imap_sync,
        # registered via register_email_sync_jobs in app.py). It is the canonical
        # autonomy_loop_log writer and carries the #1687 outage-detection. The
        # duplicate agent_loop registration was removed here to stop the 5-min
        # poll running twice (#4164).

        # Daily repo health check — README/description/topics/license for each tracked repo.
        self.scheduler.add_job(
            with_app_context(self._run_repo_health_check),
            "cron",
            hour=6,
            minute=0,
            id="forge_repo_health_check",
            name="Agent Loop: F.O.R.G.E. Repo Health Check",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Weekly GitHub public presence audit via F.O.R.G.E. (Project #247 / Task #1803).
        self.scheduler.add_job(
            with_app_context(self._run_github_presence_audit),
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            id="forge_github_presence_audit",
            name="Agent Loop: F.O.R.G.E. GitHub Presence Audit",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Tiered PR Merge Authority — F.O.R.G.E./A.R.C.H.I.E./Kytran governance.
        # Every 2 min: picks up reviewed PRs, auto-merges T1/T2, Telegrams T3.
        # Was 10 min — the last and longest wait in the chain, and the one that
        # made A.R.C.H.I.E. look absent from her own loop: a PR she had the
        # authority to merge sat up to 10 min after F.O.R.G.E. approved it, so
        # the owner merged it himself and she never got the chance. The tick is
        # cheap by construction — it hits GitHub only for reviews not yet
        # tier-processed (the `tier_processed`/`kytran_approval_sent` guard), so
        # a quiet queue costs one DB query. Authority, gates and ceilings are
        # untouched; only the latency changes.
        self.scheduler.add_job(
            with_app_context(self._run_archie_pr_review_worker),
            trigger=IntervalTrigger(minutes=2, timezone="America/Toronto"),
            id="forge_archie_pr_review",
            name="Agent Loop: Tiered PR Merge Authority (F.O.R.G.E./A.R.C.H.I.E./Kytran)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # C.O.D.E.X. — event auto-documentation (Project #272 Phase 2 / Task #2108).
        # Runs every 30 min; template-based, no LLM. Scans project_decisions
        # for undocumented rows and writes a vault_note per ADR.
        self.scheduler.add_job(
            with_app_context(self._run_codex_event_docs),
            trigger=IntervalTrigger(minutes=30),
            id="codex_event_docs",
            name="Agent Loop: C.O.D.E.X. Event Auto-Documentation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # V.I.G.I.L. — infra heartbeat (Project #272 Phase 2 / Task #2127).
        # Every 5 min — critical containers going absent must be caught fast.
        # Triggered by the 2026-04-18 NPM removal outage (KB mistake #256963).
        self.scheduler.add_job(
            with_app_context(self._run_infra_heartbeat),
            trigger=IntervalTrigger(minutes=5),
            id="vigil_infra_heartbeat",
            name="Agent Loop: V.I.G.I.L. Infrastructure Heartbeat",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # V.I.G.I.L. — external-DNS resolution monitor (Task #4571).
        # Every 2 min — catches the RECURRING OAuth/platform.claude.com DNS
        # failure live (AdGuard SERVFAIL/timeout while a control upstream
        # resolves), so the intermittent fault is captured with evidence
        # instead of self-healing before anyone looks. Telegram on classification
        # CHANGE only (never floods).
        self.scheduler.add_job(
            with_app_context(self._run_dns_monitor),
            trigger=IntervalTrigger(minutes=2),
            id="vigil_dns_monitor",
            name="Agent Loop: V.I.G.I.L. External-DNS Resolution Monitor",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_ddns),
            trigger=IntervalTrigger(minutes=15),
            id="ddns_ip_monitor",
            name="Agent Loop: DDNS Public IP Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._recover_idle_welfare),
        #     trigger=IntervalTrigger(minutes=30),
        #     id="agent_welfare_recovery",
        #     name="Agent Loop: Welfare Recovery",
        #     replace_existing=True,
        # )

        self.scheduler.add_job(
            with_app_context(self._archive_stale_notifications),
            trigger=IntervalTrigger(hours=6),
            id="agent_notification_cleanup",
            name="Agent Loop: Stale Notification Archiver",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._volunteer_idle_agents),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_idle_volunteering",
        #     name="Agent Loop: Idle Volunteering",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to security_network/jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._discover_network_devices),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_network_discovery",
        #     name="Agent Loop: Network Device Discovery",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/agent_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._update_performance_rankings),
        #     trigger=IntervalTrigger(minutes=15),
        #     id="agent_performance_rankings",
        #     name="Agent Loop: Performance Rankings",
        #     replace_existing=True,
        # )

        self.scheduler.add_job(
            with_app_context(self._check_media_schedules),
            trigger=IntervalTrigger(minutes=15),
            id="agent_media_generation",
            name="Agent Loop: Media Generation Schedules",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._media_generation_worker),
            trigger=IntervalTrigger(seconds=30),
            id="media_generation_worker",
            name="Agent Loop: Media Generation Worker (Creative & Design / M.U.S.E.)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._portrait_refinement_worker),
            trigger=IntervalTrigger(seconds=30),
            id="portrait_refinement_worker",
            name="Agent Loop: Portrait Refinement Worker (Creative & Design / M.U.S.E.)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # #4661 Cloud Comparison Lane: drains approved cloud A/B runs (dispatch
        # local+cloud, local judge, complete/cancel). Toggle via
        # work:ab_compare_worker:enabled (work_control_service); no-ops when
        # there are no pending ab_compare runs.
        self.scheduler.add_job(
            with_app_context(self.ab_compare_worker),
            trigger=IntervalTrigger(seconds=30),
            id="ab_compare_worker",
            name="Agent Loop: Cloud A/B Comparison Worker (Agent Academy)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._model_dispatch_worker),
            trigger=IntervalTrigger(seconds=15),
            id="model_dispatch_worker",
            name="Agent Loop: Model-Affinity Dispatch Queue Worker (Department HQ)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        from apscheduler.triggers.cron import CronTrigger as _CronTrigger

        self.scheduler.add_job(
            with_app_context(self._website_deploy_worker),
            trigger=_CronTrigger(hour=3, minute=0, timezone="America/Toronto"),
            id="website_deploy_worker",
            name="Agent Loop: Website Deploy (Operations / B.A.S.E.)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._compute_media_analytics),
            trigger=IntervalTrigger(hours=1),
            id="media_analytics_snapshot",
            name="Agent Loop: Media Analytics Snapshot",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._process_agent_emails),
            trigger=IntervalTrigger(minutes=5),
            id="agent_email_processing",
            name="Agent Loop: Gmail Processing",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._process_world_events),
            trigger=IntervalTrigger(seconds=30),
            id="game_world_event_processor",
            name="Agent Loop: Game World Events",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._update_market_prices),
            trigger=IntervalTrigger(minutes=5),
            id="game_market_price_update",
            name="Agent Loop: Game Market Prices",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._agent_calendar_drive_tasks),
            trigger=IntervalTrigger(minutes=15),
            id="agent_calendar_drive",
            name="Agent Loop: Calendar + Drive Autonomy",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._update_stock_prices),
            trigger=IntervalTrigger(minutes=5),
            id="stock_price_updater",
            name="Agent Loop: Stock Price Updater",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        # Phase 5: Moved to consciousness/jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._deduplicate_knowledge),
        #     trigger=IntervalTrigger(hours=24),
        #     id="knowledge_deduplication",
        #     name="Agent Loop: Knowledge Deduplication",
        #     replace_existing=True,
        # )
        # Phase 5: Moved to consciousness/jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._index_claude_sessions),
        #     trigger=IntervalTrigger(hours=12),
        #     id="session_indexer",
        #     name="Agent Loop: Claude Session Indexer",
        #     replace_existing=True,
        # )
        self.scheduler.add_job(
            with_app_context(self._update_module_docs),
            trigger=IntervalTrigger(hours=24),
            id="module_docs_updater",
            name="Agent Loop: Module Documentation",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._track_git_changes),
            trigger=IntervalTrigger(minutes=30),
            id="git_change_tracker",
            name="Agent Loop: Git Change Tracker",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        self.scheduler.add_job(
            with_app_context(self._monitor_ssh_logins),
            trigger=IntervalTrigger(minutes=5),
            id="agent_ssh_monitor",
            name="Agent Loop: SSH Login Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Phase 5: Moved to security_network/jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._run_security_audit),
        #     trigger=CronTrigger(day_of_week="sun", hour=3),
        #     id="agent_security_audit",
        #     name="Agent Loop: Weekly Security Audit",
        #     replace_existing=True,
        # )
        # self.scheduler.add_job(
        #     with_app_context(self._check_ssl_expiry),
        #     trigger=IntervalTrigger(hours=24),
        #     id="agent_ssl_expiry_check",
        #     name="Agent Loop: SSL Certificate Expiry Check",
        #     replace_existing=True,
        # )
        # self.scheduler.add_job(
        #     with_app_context(self._daily_dns_report),
        #     trigger=CronTrigger(hour=7, minute=0),
        #     id="agent_daily_dns_report",
        #     name="Agent Loop: Daily DNS Report",
        #     replace_existing=True,
        # )
        # self.scheduler.add_job(
        #     with_app_context(self._detect_query_spike),
        #     trigger=IntervalTrigger(hours=1),
        #     id="agent_query_spike_detect",
        #     name="Agent Loop: DNS Query Spike Detection",
        #     replace_existing=True,
        # )
        # self.scheduler.add_job(
        #     with_app_context(self._check_camera_anomaly),
        #     trigger=IntervalTrigger(hours=1),
        #     id="agent_camera_anomaly",
        #     name="Agent Loop: Camera Motion Anomaly",
        #     replace_existing=True,
        # )
        # self.scheduler.add_job(
        #     with_app_context(self._run_auto_block),
        #     trigger=IntervalTrigger(minutes=15),
        #     id="agent_auto_block",
        #     name="Agent Loop: Auto-Block Pipeline",
        #     replace_existing=True,
        # )
        self.scheduler.add_job(
            with_app_context(self._check_mission_schedule),
            trigger=IntervalTrigger(minutes=5),
            id="agent_mission_schedule",
            name="Agent Loop: Mission Profile Schedule",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #40 — Daily Code Metrics Scan (3:00 AM)
        # self.scheduler.add_job(
        #     with_app_context(self._daily_code_metrics_scan),
        #     trigger=CronTrigger(hour=3, minute=0),
        #     id="agent_code_metrics",
        #     name="Agent Loop: Daily Code Metrics Scan",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #41 — Pattern Compliance Check (4:00 AM)
        # self.scheduler.add_job(
        #     with_app_context(self._pattern_compliance_check),
        #     trigger=CronTrigger(hour=4, minute=0),
        #     id="agent_pattern_compliance",
        #     name="Agent Loop: Pattern Compliance Check",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/fleet_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._check_fleet_health),
        #     trigger=IntervalTrigger(seconds=30),
        #     id="agent_fleet_health",
        #     name="Agent Loop: Fleet Health Monitor",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/fleet_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._check_mesh_health),
        #     trigger=IntervalTrigger(seconds=60),
        #     id="agent_mesh_health",
        #     name="Agent Loop: Mesh VPN Health Monitor",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/fleet_jobs.py
        # self.scheduler.add_job(
        #     with_app_context(self._save_model_state),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_model_state_save",
        #     name="Agent Loop: Model State Persistence",
        #     replace_existing=True,
        # )

        self.scheduler.add_job(
            with_app_context(self._hourly_uncommitted_check),
            trigger=IntervalTrigger(hours=1),
            id="agent_uncommitted_check",
            name="Agent Loop: Uncommitted Change Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Job #47 — Chat memory extraction
        # DISABLED 2026-04-17: depends on `directory_agent_memories` table that
        # was dropped when the `directory` (Employee Directory) module was
        # disabled in module_registry. Leaving it on spams
        # "relation directory_agent_memories does not exist" every 2 min.
        # Re-enable after the module is restored OR port the logic to
        # archie_chat's conversation_history table.
        # self.scheduler.add_job(
        #     _process_chat_memories,
        #     trigger=IntervalTrigger(minutes=2),
        #     id="job_47_chat_memories",
        #     name="Chat memory extraction",
        #     replace_existing=True,
        # )

        # Job #48 — Auto-execute approved dev pipeline proposals
        self.scheduler.add_job(
            with_app_context(self._auto_execute_proposals),
            trigger=IntervalTrigger(minutes=30),
            id="agent_auto_execute_proposals",
            name="Agent Loop: Auto-Execute Dev Proposals",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Phase 5: Moved to consciousness/jobs.py
        # Job #49 — Consciousness analysis batch (every 6h)
        # self.scheduler.add_job(
        #     with_app_context(self._consciousness_analysis_batch),
        #     trigger=IntervalTrigger(hours=6),
        #     id="agent_consciousness_analysis",
        #     name="Agent Loop: Consciousness Analysis Batch",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to consciousness/jobs.py
        # Job #50 — Consciousness embedding batch (every 30min, 200 items/batch)
        # self.scheduler.add_job(
        #     with_app_context(self._consciousness_embedding_batch),
        #     trigger=IntervalTrigger(minutes=30),
        #     id="agent_consciousness_embedding",
        #     name="Agent Loop: Consciousness Embedding Batch",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #51 — Daily Code Health Digest via Telegram (8:00 AM)
        # self.scheduler.add_job(
        #     with_app_context(self._daily_code_health_digest),
        #     trigger=CronTrigger(hour=8, minute=0),
        #     id="agent_code_health_digest",
        #     name="Agent Loop: Daily Code Health Digest",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #55 — Daily Code Health Scan (2:00 AM, before 8 AM digest)
        # self.scheduler.add_job(
        #     with_app_context(self._daily_code_health_scan),
        #     trigger=CronTrigger(hour=2, minute=0),
        #     id="agent_code_health_scan",
        #     name="Agent Loop: Daily Code Health Scan",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #58 — Automated Module Audit (daily 3:30 AM, after Job #40 snapshot)
        # self.scheduler.add_job(
        #     with_app_context(self._automated_module_audit),
        #     trigger=CronTrigger(hour=3, minute=30),
        #     id="agent_automated_module_audit",
        #     name="Agent Loop: Automated Module Audit",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to dev_hq/jobs.py
        # Job #52 — Competitor landscape auto-scan (every 2 weeks)
        # self.scheduler.add_job(
        #     with_app_context(self._competitor_landscape_scan),
        #     trigger=IntervalTrigger(days=14),
        #     id="agent_competitor_scan",
        #     name="Agent Loop: Competitor Landscape Scan",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to consciousness/jobs.py
        # Job #54 — Skill sync: extract learned skills from KB to Claude rules
        # self.scheduler.add_job(
        #     with_app_context(self._sync_learned_skills),
        #     trigger=IntervalTrigger(hours=6),
        #     id="agent_skill_sync",
        #     name="Agent Loop: Skill Sync to Claude",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to consciousness/jobs.py
        # Job #55 — GitHub auto-pull: refresh tracked repos and re-index changed files
        # self.scheduler.add_job(
        #     with_app_context(self._github_auto_pull),
        #     trigger=IntervalTrigger(hours=12),
        #     id="agent_github_auto_pull",
        #     name="Agent Loop: GitHub Auto-Pull & Re-Index",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to consciousness/jobs.py
        # Job #56 — Skill analyzer: AI-powered quality scoring for discovered skills
        # self.scheduler.add_job(
        #     with_app_context(self._analyze_discovered_skills),
        #     trigger=IntervalTrigger(hours=6, start_date="2026-01-01 01:00:00"),
        #     id="agent_skill_analyzer",
        #     name="Agent Loop: Skill Analyzer (Bridge AI)",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to security_network/jobs.py
        # Job #57 — Compliance scan: STIG rule evaluation every 6 hours
        # self.scheduler.add_job(
        #     with_app_context(self._run_scheduled_compliance_scan),
        #     trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:00:00"),
        #     id="agent_compliance_scan",
        #     name="Agent Loop: Compliance Scan",
        #     replace_existing=True,
        # )

        # Job #59 — Dependabot vulnerability scan: poll alerts and triage every 6 hours
        self.scheduler.add_job(
            with_app_context(self._run_dependabot_scan),
            trigger=IntervalTrigger(hours=6),
            id="dependabot_scan",
            name="Agent Loop: Dependabot Vulnerability Scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_market_watch_cycle),
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="0,30",
                timezone="America/New_York",
            ),
            id="market_watch_cycle",
            name="Agent Loop: M.A.R.K.E.T. Trading Cycle (Market Hours)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Phase 5: Moved to security_network/jobs.py
        # Job #58 — Auto-remediation: fix low-risk compliance failures 30min after scan
        # self.scheduler.add_job(
        #     with_app_context(self._run_auto_remediation),
        #     trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:30:00"),
        #     id="agent_auto_remediation",
        #     name="Agent Loop: Compliance Auto-Remediation",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to consciousness/jobs.py
        # --- Migrated from consciousness_scheduler (APScheduler in app.py) ---
        # Conversation consolidation, improvement detection, daily self-reflection,
        # weekly memory consolidation — all 4 now registered via
        # register_consciousness_jobs() below.

        # --- Migrated from infrastructure scheduler (app.py) ---

        # Batch medium issues (Sunday 2 AM)
        self.scheduler.add_job(
            with_app_context(self._batch_medium_issues),
            trigger=CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="America/Toronto"),
            id="agent_batch_medium_issues",
            name="Agent Loop: Weekly Code Issue Batch",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Auto log ingestion (every 30 min)
        self.scheduler.add_job(
            with_app_context(self._auto_log_ingestion),
            trigger=IntervalTrigger(minutes=30),
            id="agent_auto_log_ingestion",
            name="Agent Loop: Auto Log Ingestion",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Weekly dependency scan (Sunday 4 AM)
        self.scheduler.add_job(
            with_app_context(self._weekly_dependency_scan),
            trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="America/Toronto"),
            id="agent_weekly_dependency_scan",
            name="Agent Loop: Weekly Dependency Scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # DISABLED 2026-04-14: 77 fails/day, "No module named tools.dev_hq" — see Project #261
        # self.scheduler.add_job(
        #     with_app_context(self._health_probe),
        #     trigger=IntervalTrigger(minutes=15),
        #     id="agent_health_probe",
        #     name="Agent Loop: Service Health Probe",
        #     replace_existing=True,
        # )

        # Crew wellness tick (every 5 min)
        self.scheduler.add_job(
            with_app_context(self._crew_wellness_tick),
            trigger=IntervalTrigger(minutes=5),
            id="agent_crew_wellness_tick",
            name="Agent Loop: Crew Wellness Tick",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Ollama model health (every 30 min)
        self.scheduler.add_job(
            with_app_context(self._ollama_model_health),
            trigger=IntervalTrigger(minutes=30),
            id="agent_ollama_model_health",
            name="Agent Loop: Ollama Model Health",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Ollama placement telemetry (every 5 min)
        self.scheduler.add_job(
            with_app_context(self._ollama_placement_telemetry),
            trigger=IntervalTrigger(minutes=5),
            id="ollama_placement_telemetry",
            name="Agent Loop: Ollama Placement Telemetry",
            coalesce=True,
            replace_existing=True,
            max_instances=1,
        )

        # Media queue cleanup (every 1h)
        self.scheduler.add_job(
            with_app_context(self._media_queue_cleanup),
            trigger=IntervalTrigger(hours=1),
            id="agent_media_queue_cleanup",
            name="Agent Loop: Media Queue Cleanup",
            misfire_grace_time=300,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Media export cleanup (every 1h)
        self.scheduler.add_job(
            with_app_context(self._media_export_cleanup),
            trigger=IntervalTrigger(hours=1),
            id="agent_media_export_cleanup",
            name="Agent Loop: Media Export Cleanup",
            misfire_grace_time=300,
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Phase 5: Moved to services/fleet_jobs.py
        # Job #59 — Standalone health monitoring: ping KSM every 60s, alert on downtime
        # self.scheduler.add_job(
        #     with_app_context(self._check_standalone_health),
        #     trigger=IntervalTrigger(seconds=60),
        #     id="agent_standalone_health",
        #     name="Agent Loop: Standalone Health Monitor",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/fleet_jobs.py
        # Job #60 — Department metrics rollup: daily at 2:00 AM, owned by S.P.E.C.T.R.A.
        # self.scheduler.add_job(
        #     with_app_context(self._department_metrics_rollup),
        #     trigger=CronTrigger(hour=2, minute=0),
        #     id="department_metrics_rollup",
        #     name="Agent Loop: Department Metrics Rollup",
        #     replace_existing=True,
        # )

        # Phase 5: Moved to services/fleet_jobs.py
        # Job #61: Fleet SSL wildcard cert renewal (daily 03:00 UTC)
        # self.scheduler.add_job(
        #     with_app_context(self._renew_fleet_ssl),
        #     trigger=CronTrigger(hour=3, minute=0),
        #     id="fleet_ssl_renewal",
        #     name="Agent Loop: Fleet SSL Renewal",
        #     replace_existing=True,
        # )

        # Job #62: Social video content generation (every 4 hours)
        self.scheduler.add_job(
            with_app_context(self._social_video_generate_content),
            "interval",
            hours=4,
            id="social_video_generate",
            name="Social Video: Generate Content",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Job #63: Social video auto-approve (every 15 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_auto_approve),
            "interval",
            minutes=15,
            id="social_video_auto_approve",
            name="Social Video: Auto-Approve",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Job #64: Social video publish scheduled items (every 5 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_publish),
            "interval",
            minutes=5,
            id="social_video_publish",
            name="Social Video: Publish Scheduled",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Job #65: AutoShorts slideshow render (every 2 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_slideshow_render),
            "interval",
            minutes=2,
            id="social_video_slideshow_render",
            name="Social Video: Slideshow Renderer",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Job #66: S.I.G.N.A.L. Content Auto-Suggest (daily 8am)
        self.scheduler.add_job(
            with_app_context(self._social_content_auto_suggest),
            "cron",
            hour=8,
            minute=0,
            id="social_content_auto_suggest",
            name="S.I.G.N.A.L.: Content Auto-Suggest",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # ── V.I.G.I.L. Security & Compliance Department Jobs ──

        self.scheduler.add_job(
            with_app_context(self._vigilil_network_health),
            trigger=IntervalTrigger(seconds=60),
            id="vigilil_network_health",
            name="V.I.G.I.L.: Network Health Monitor",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_traffic_aggregator),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_traffic_aggregator",
            name="V.I.G.I.L.: Traffic Aggregator",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_nagios_sync),
            trigger=IntervalTrigger(minutes=2),
            id="vigilil_nagios_sync",
            name="V.I.G.I.L.: Nagios Sync",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_device_watcher),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_device_watcher",
            name="V.I.G.I.L.: Device Watcher",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_dns_anomaly),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_dns_anomaly",
            name="V.I.G.I.L.: DNS Anomaly Detector",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_log_health),
            trigger=IntervalTrigger(minutes=15),
            id="vigilil_log_health",
            name="V.I.G.I.L.: Log Health Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_daily_report),
            trigger=CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
            id="vigilil_daily_report",
            name="V.I.G.I.L.: Daily Bandwidth Reporter",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_threat_responder),
            trigger=IntervalTrigger(seconds=30),
            id="vigilil_threat_responder",
            name="V.I.G.I.L.: Threat Responder",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_vpn_scan),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_vpn_scan",
            name="V.I.G.I.L.: VPN Usage Monitor",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_bandwidth_alerts),
            trigger=IntervalTrigger(minutes=30),
            id="vigilil_bandwidth_alerts",
            name="V.I.G.I.L.: Bandwidth Threshold Monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # All module jobs registered via Department HQ (centralized — Decision #440)
        try:
            from tools.department_hq.jobs import register_department_hq_jobs

            register_department_hq_jobs(self.scheduler, self.flask_app)
            logger.info("[AgentLoop] All department jobs registered via Department HQ")
        except Exception as e:
            logger.error("[AgentLoop] Failed to register department jobs: %s", e)

        # Job: Knowledge Quality Review (every 30 min — accelerated backfill)
        self.scheduler.add_job(
            with_app_context(self._run_quality_review),
            trigger=IntervalTrigger(minutes=30),
            id="quality_review",
            name="Knowledge Quality Review",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        logger.info("Registered job: Knowledge Quality Review (every 30m)")

        # Job: C.R.E.E.D. Governance Reporter (every 5 min)
        self.scheduler.add_job(
            with_app_context(self._creed_governance_reporter),
            trigger=IntervalTrigger(minutes=5),
            id="creed_governance_reporter",
            name="C.R.E.E.D. Governance Reporter",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Registered job: C.R.E.E.D. Governance Reporter (every 5m)")

        self.scheduler.add_job(
            with_app_context(self._run_login_anomaly_check),
            trigger=IntervalTrigger(minutes=30),
            id="login_anomaly_check",
            name="Agent Loop: Login Anomaly Check",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )

        # Job #75: Cross-Watch alert generator — match signals to user follows (Task #3023)
        try:
            from tools.cross_watch.alert_generator import generate_cross_watch_alerts as _cw_gen

            self.scheduler.add_job(
                with_app_context(_cw_gen),
                trigger=IntervalTrigger(minutes=15),
                id="cross_watch_alert_generator",
                name="Cross-Watch: Alert Generator",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("Registered job: Cross-Watch Alert Generator (every 15m)")
        except Exception as _cw_import_err:
            logger.warning(
                "Could not register cross_watch_alert_generator — migration may not have run: %s",
                _cw_import_err,
            )

        # Job #76: Email HQ daily digest → Telegram (T3288 + Slice 5).
        # Runs every 15 min and self-gates on the tunable send time
        # (mailhq:digest:time) so the schedule is adjustable from Mail HQ with no
        # redeploy; the job sends at most once per day.
        self.scheduler.add_job(
            with_app_context(self._email_morning_digest),
            trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
            id="email_morning_digest",
            name="Email HQ: Daily Digest",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        logger.info("Registered job: Email HQ Daily Digest (tunable time, default 08:00 ET)")

        # Job #77: Codex Auto-Queue — scan pending tasks in Codex-scoped projects
        # and auto-delegate one per cycle to the host Codex poller (Phase B).
        # Gated by platform_settings 'codex_auto_queue_enabled' = 'true'.
        # Project IDs from 'codex_auto_queue_project_ids' (comma-separated).
        # Every 30 min (was daily 01:00) — safe at this cadence because the
        # K.I.N. load gates inside the job (daily run cap from agent_budgets,
        # queue depth, owner-review backpressure, WP-007 failure standby)
        # decide whether anything is actually queued.
        self.scheduler.add_job(
            with_app_context(self._codex_auto_queue),
            trigger="interval",
            minutes=30,
            jitter=120,
            id="codex_auto_queue",
            name="Agent Loop: Codex Auto-Queue (K.I.N.-gated, every 30 min)",
            max_instances=1,
            replace_existing=True,
            coalesce=True,
        )
        logger.info("Registered job: Codex Auto-Queue (every 30 min, K.I.N.-gated)")

        # Carbon Footprint Monitor — CREED environmental pillar (#3254)
        # Runs every hour, aggregates inference kWh/CO2, pushes to CREED environmental pillar.
        def _run_carbon_footprint():
            with self.flask_app.app_context():
                from services.carbon_footprint_service import run_carbon_footprint_job

                result = run_carbon_footprint_job()
                logger.info("[CarbonJob] %s", result)

        self.scheduler.add_job(
            _run_carbon_footprint,
            "interval",
            hours=1,
            id="carbon_footprint_job",
            name="Carbon Footprint Monitor — CREED environmental pillar (Project #358 #3254)",
            max_instances=1,
            coalesce=True,
        )
        logger.info("Registered job: Carbon Footprint Monitor (every 1h, CREED environmental)")

        self._running = True
        logger.info("Agent loop started with 78 jobs")

    def _update_stock_prices(self):
        """Job #27: DISABLED — StockBot migrated to Kytran Market Watch (standalone).
        Remove this stub and its scheduler registration once Market Watch has its own job system.
        """
        pass

    def _check_media_schedules(self):
        """Check agent media generation schedules and trigger if due."""
        from datetime import datetime

        try:
            from croniter import croniter
            from database import get_db_cursor
            from tools.media_studio.services.agent_media_service import (
                agent_generate,
                GLOBAL_DAILY_CAP,
                _get_daily_count,
            )

            if _get_daily_count() >= GLOBAL_DAILY_CAP:
                return

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT agent_name, media_type, schedule_cron, last_generated_at "
                    "FROM media_agent_config WHERE enabled = TRUE"
                )
                configs = cur.fetchall()

            now = datetime.now()
            for row in configs:
                agent_name = row[0] if not hasattr(row, "get") else row["agent_name"]
                cron_expr = row[2] if not hasattr(row, "get") else row["schedule_cron"]
                last_gen = row[3] if not hasattr(row, "get") else row["last_generated_at"]
                try:
                    cron = croniter(cron_expr, now)
                    prev_fire = cron.get_prev(datetime)
                    if last_gen is None or prev_fire > last_gen:
                        result = agent_generate(agent_name)
                        if "error" in result:
                            logger.debug(
                                "Agent media skip %s: %s",
                                agent_name,
                                result["error"],
                            )
                        else:
                            logger.info(
                                "Agent media generated for %s: id=%s",
                                agent_name,
                                result.get("id"),
                            )
                except Exception as e:
                    logger.error("Agent media schedule error for %s: %s", agent_name, e)
        except ImportError:
            logger.warning("croniter not available — skipping media schedules")
        except Exception as e:
            logger.error("Agent media schedule check failed: %s", e)

    def _media_generation_worker(self):
        """Process pending ComfyUI media generation queue entries.

        Routes through Department HQ → P.I.X.E.L. (image_generation skill, Creative & Design).
        P.I.X.E.L. owns ComfyUI — warms it up if stopped before generating.
        VRAM is managed by P.I.X.E.L.: ComfyUI needs GPU swap from Ollama first.
        """
        from database import get_db_cursor

        # Step 1: Ask DHQ which agent handles image_generation (P.I.X.E.L.).
        # Wakes the agent if barracked and confirms Creative & Design is staffed.
        _pixel_agent = None
        _dhq_defer = False  # set when welfare says there is no capacity (#5345)
        try:
            from services.department_coordinator import get_coordinator as _get_coord

            coord = _get_coord()
            agent = coord.select_agent("image_generation", "Creative & Design")
            if agent:
                _pixel_agent = agent
                logger.info(
                    "media_generation_worker: %s (id=%s) selected via DHQ for image_generation",
                    agent.get("name", "?"),
                    agent.get("id", "?"),
                )
            else:
                # DEFER, don't "proceed anyway" (#5345). select_agent already scores
                # candidates on stress / energy / utilisation and returns None when
                # nothing qualifies — so a None here IS the welfare verdict, and this
                # drain executing regardless was precisely the ADR-002 bypass: work
                # ran with no welfare / C.R.E.E.D. / cost gating, attributed to a
                # hardcoded fallback (agent_id 13, "P.I.X.E.L.").
                #
                # Deferring is NON-DESTRUCTIVE: we return before the claim UPDATE, so
                # rows stay 'pending' and the next cycle retries. Nothing is failed
                # and nothing is lost — the queue waits for capacity, which is the
                # entire point of a welfare gate.
                _dhq_defer = True
                logger.info(
                    "media_generation_worker: no image_generation agent available "
                    "(welfare) — deferring this cycle, rows stay pending"
                )
        except Exception as dhq_err:
            # An ERROR is not a "no". A coordinator/import failure is an
            # infrastructure fault, not a capacity verdict — treating it as a denial
            # would let a single bug stall ALL image generation indefinitely. Fail
            # OPEN here; the pre-existing fallback attribution still applies.
            logger.warning("media_generation_worker: DHQ agent lookup failed (non-blocking): %s", dhq_err)

        # Step 2: does the queue actually hold ComfyUI-bound work? The hub wake
        # below is gated on this (#5277): with an EMPTY queue the worker used to
        # wake the hub container anyway whenever fleet ComfyUI was unreachable —
        # e.g. the whole 8PM–6AM hardware-rest window — and the container claims
        # GPU VRAM the moment it starts (compose reserves an nvidia device), so
        # agent inference lost the card to an SDXL load that never arrives.
        # Cloud-contractor jobs (params.provider set to a non-comfyui value)
        # never need a local ComfyUI, so they are excluded from this peek; a
        # peek failure means no wake this tick, which is safe — the generate
        # path cold-starts via comfyui_lifecycle.ensure_running itself.
        _next_model = None
        _comfyui_pending = False
        try:
            from database import get_db_cursor as _gdc

            with _gdc() as (_, _cur):
                _cur.execute(
                    "SELECT params->>'model' AS model FROM media_generation_queue "
                    "WHERE status='pending' AND (params->>'provider'='comfyui' OR params->>'provider' IS NULL) "
                    "ORDER BY created_at ASC LIMIT 1"
                )
                _row = _cur.fetchone()
                if _row:
                    _comfyui_pending = True
                    _next_model = _row["model"]
        except Exception:
            pass

        # Step 3: Prefer fleet ComfyUI (RTX Starship) over hub Quadro M4000 —
        # only consulted when there is ComfyUI-bound work to place.
        _fleet_available = False
        if _comfyui_pending:
            try:
                from tools.media_studio.services.comfyui_manager import get_best_comfyui_url

                _fleet_url, _fleet_node = get_best_comfyui_url(model_name=_next_model)
                if _fleet_node:
                    logger.info(
                        "media_generation_worker: fleet ComfyUI on %s — skipping hub warmboot",
                        _fleet_node,
                    )
                    _fleet_available = True
            except Exception as _fe:
                logger.debug("media_generation_worker: fleet ComfyUI check failed: %s", _fe)

        if _comfyui_pending and not _fleet_available:
            # Fall back to hub ComfyUI — warm up container if stopped. This is
            # THE arbitration point between image gen and agent inference on the
            # hub GPUs: the wake fires only when a real ComfyUI job is pending
            # and no fleet node can take it, and while the container is up
            # model_service.gpu_placement_options bars new LLM GPU admissions
            # (#5276). The idle-stop paths return the card to inference.
            try:
                from ai_bridge.comfyui_service import get_comfyui_service

                svc = get_comfyui_service()
                if svc.is_stopped():
                    logger.info("media_generation_worker: ComfyUI stopped — P.I.X.E.L. warming up container")
                    healthy = svc.wake_if_stopped()
                    if not healthy:
                        logger.warning(
                            "media_generation_worker: ComfyUI warmboot failed — leaving jobs pending for next tick"
                        )
                        return
                    logger.info("media_generation_worker: ComfyUI healthy after warmboot")
            except Exception as wake_err:
                logger.warning("media_generation_worker: ComfyUI warmboot check failed: %s", wake_err)

        # WELFARE GATE (#5345). BEFORE the claim UPDATE below, so rows keep
        # status='pending' and the next 30s cycle simply retries them — deferring
        # never fails or loses a job.
        #
        # It must also RECLAIM VRAM on the way out. The normal idle-stop lives in
        # the `if not claimed:` branch AFTER the claim, so returning here would skip
        # it and leave ComfyUI resident holding VRAM that Ollama wants — exactly the
        # waste #5277 exists to prevent. Deferring means we are generating nothing,
        # which is precisely when the container should not be up. Best-effort: an
        # idle-stop failure must not turn a clean deferral into an error.
        if _dhq_defer:
            try:
                from ai_bridge.comfyui_service import get_comfyui_service

                get_comfyui_service().stop_if_idle()
            except Exception as _stop_err:
                logger.debug("media_generation_worker: idle-stop on defer skipped: %s", _stop_err)
            logger.info(
                "media_generation_worker: deferring claim — Creative & Design has no "
                "available image_generation agent; pending rows are left untouched for the next cycle"
            )
            return

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE media_generation_queue
                    SET status = 'dispatched', started_at = NOW()
                    WHERE id IN (
                        SELECT id FROM media_generation_queue
                        WHERE status = 'pending'
                        -- All image/video/audio providers consumed here: comfyui (local SDXL),
                        -- cloud contractors (pollinations, openai, stability_ai, etc).
                        -- generate_via_comfyui branches on params.provider.
                        --
                        -- LIMIT 3 — claim up to 3 jobs per cycle so different
                        -- jobs can dispatch to different ComfyUI backends
                        -- (hub Quadro, Starship-246 RTX 3070, Starship-245 RTX 3050).
                        -- comfyui_manager.get_best_comfyui_url(model_name) picks
                        -- per-model, so SDXL → 8GB nodes, SD 1.5 → any node.
                        -- FOR UPDATE SKIP LOCKED guarantees exclusive ownership.
                        ORDER BY created_at ASC
                        LIMIT 3
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING id, media_type, params
                    """,
                )
                claimed = cur.fetchall()

            if not claimed:
                # No pending ComfyUI jobs — P.I.X.E.L. goes idle, stop container
                # to reclaim VRAM for Ollama text models.
                try:
                    from ai_bridge.comfyui_service import get_comfyui_service

                    get_comfyui_service().stop_if_idle()
                except Exception as _stop_err:
                    logger.debug("media_generation_worker: idle-stop skipped: %s", _stop_err)
                return

            for row in claimed:
                queue_id = row["id"]
                media_type = row["media_type"]
                _gen_start = time.time()
                _gen_success = False
                try:
                    from tools.media_studio.services.generation_service import (
                        generate_via_comfyui,
                        generate_video_via_comfyui,
                        generate_audio,
                    )

                    if media_type == "video":
                        _gen_result = generate_video_via_comfyui(queue_id)
                    elif media_type == "audio":
                        _gen_result = generate_audio(queue_id)
                    else:
                        _gen_result = generate_via_comfyui(queue_id)
                    _gen_success = _gen_result is not None
                except Exception as e:
                    err_str = str(e)
                    # ComfyUI down = transient — reset to pending so next tick retries.
                    # Permanent errors (bad prompt, missing model) = fail immediately.
                    is_transient = (
                        "unavailable" in err_str.lower()
                        or "connection" in err_str.lower()
                        or "timeout" in err_str.lower()
                    )
                    if is_transient:
                        logger.warning(
                            "media_generation_worker: queue %s — ComfyUI unavailable, resetting to pending: %s",
                            queue_id,
                            err_str,
                        )
                        with get_db_cursor(commit=True) as (conn, cur):
                            cur.execute(
                                """
                                UPDATE media_generation_queue
                                SET status = 'pending', started_at = NULL,
                                    error_message = %s
                                WHERE id = %s
                                """,
                                ("Waiting for ComfyUI — will retry automatically", queue_id),
                            )
                    else:
                        logger.exception("media_generation_worker: queue %s failed: %s", queue_id, e)
                        with get_db_cursor(commit=True) as (conn, cur):
                            cur.execute(
                                """
                                UPDATE media_generation_queue
                                SET status = 'failed', error_message = %s, completed_at = NOW()
                                WHERE id = %s
                                """,
                                (err_str, queue_id),
                            )
                finally:
                    # Attribute job to P.I.X.E.L. in task_execution_log so DHQ
                    # Dispatch Traffic panel + performance metrics reflect ComfyUI work.
                    _dur_ms = int((time.time() - _gen_start) * 1000)
                    try:
                        _pa = _pixel_agent or {}
                        _pid = _pa.get("id") or 13  # P.I.X.E.L. fallback agent_id
                        _pname = _pa.get("name") or "P.I.X.E.L."
                        # Read model + fleet_node from queue row (may have been updated during gen)
                        with get_db_cursor() as (_, _lc):
                            _lc.execute(
                                "SELECT params->>'model' AS model, "
                                "params->>'fleet_node' AS fleet_node "
                                "FROM media_generation_queue WHERE id = %s",
                                (queue_id,),
                            )
                            _qr = _lc.fetchone() or {}
                        _model = _qr.get("model") or "comfyui"
                        _fleet_name = _qr.get("fleet_node")
                        # Resolve fleet node DB id for node_used_id column
                        _node_db_id = None
                        if _fleet_name:
                            try:
                                with get_db_cursor() as (_, _nc):
                                    _nc.execute(
                                        "SELECT id FROM remote_nodes WHERE node_name = %s LIMIT 1",
                                        (_fleet_name,),
                                    )
                                    _nr = _nc.fetchone()
                                    if _nr:
                                        _node_db_id = _nr["id"]
                            except Exception:
                                pass
                        with get_db_cursor(commit=True) as (_, _tc):
                            _tc.execute(
                                """INSERT INTO task_execution_log
                                   (agent_id, agent_name, model_used, duration_ms, success,
                                    capability, node_used_id, module_source)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    _pid,
                                    _pname,
                                    _model,
                                    _dur_ms,
                                    _gen_success,
                                    "image_generation",
                                    _node_db_id,
                                    "media_studio",
                                ),
                            )
                        if _gen_success:
                            try:
                                from services.agent_service import increment_usage

                                increment_usage(_pid)
                            except Exception:
                                pass
                    except Exception as _tel_err:
                        logger.debug("media_generation_worker: task_execution_log write failed: %s", _tel_err)
        except Exception as e:
            logger.error("media_generation_worker error: %s", e)

    def _website_deploy_worker(self):
        """Daily full-site deploy to Hostinger for all public websites.

        Operations & Infrastructure — B.A.S.E. Director. Runs daily at 03:00.
        QUEUES kytranempowerment.com and creed-ai.org for the Hostinger push in
        sequence — it does NOT push bytes itself. The only working push is the
        hosting_deployStaticWebsite MCP tool via the /deploy-website skill, so
        this worker's success means "queued", never "deployed"; only
        deploy_service.mark_deploy_pushed() may write 'deployed' (2026-07-28
        audit: this worker used to overwrite the status with a bare 'success',
        which read as a completed deploy for a push that had not happened).
        Also triggerable manually via Repair Bay → Ship → Website tab.
        """
        from database import get_db_cursor
        from services.deploy_service import changed_files_since, last_push_iso, run_deploy_pipeline
        import datetime

        SITES = [
            {
                "domain": "kytranempowerment.com",
                "source": "/mnt/archie_brain/website/kytranempowerment.com",
                "verify_url": "https://kytranempowerment.com",
            },
            {
                "domain": "creed-ai.org",
                "source": "/mnt/archie_brain/website/creed-ai.org",
                "verify_url": "https://creed-ai.org",
            },
        ]

        for site in SITES:
            domain = site["domain"]
            key_ts = f"website_deploy_last_run_{domain}"
            key_st = f"website_deploy_last_status_{domain}"
            failed = False
            try:
                # REAL changed files since the last confirmed push — classify_risk
                # needs file paths to classify anything. This used to pass the
                # constants ["assets/portraits/", "data/"], which have no suffix
                # and so ALWAYS returned approval_required: the daily deploy asked
                # for approval whatever had (or had not) changed, while the
                # translation scanner auto-deployed the same files by passing real
                # .json paths. Falls back to the directory list when there is no
                # recorded push yet — unknown contents must still ask.
                since = last_push_iso(domain)
                changed = changed_files_since(site["source"], since) if since else []
                nothing_to_do = False
                if not since:
                    changed_files = ["assets/portraits/", "data/"]
                    logger.info("[WebsiteDeploy] %s has no recorded push — treating as unknown", domain)
                elif not changed:
                    # Nothing changed — do NOT queue a deploy, but this run still
                    # HAPPENED and must stamp key_ts below. An early `continue`
                    # here would freeze website_deploy_last_run_* on a perfectly
                    # healthy no-op, so "when did the deploy worker last run?"
                    # would answer with a stale timestamp — the same
                    # status-that-cannot-tell-the-truth bug this whole change
                    # set out to remove. (F.O.R.G.E. flagged it on PR #2533.)
                    nothing_to_do = True
                    logger.info("[WebsiteDeploy] %s unchanged since %s — nothing to queue", domain, since)
                else:
                    changed_files = changed
                    logger.info("[WebsiteDeploy] %s: %d file(s) changed since %s", domain, len(changed), since)

                if not nothing_to_do:
                    result = run_deploy_pipeline(
                        "deploy_static",
                        {
                            "domain": domain,
                            "source_path": site["source"],
                            "verify_url": site["verify_url"],
                            "changed_files": changed_files,
                        },
                    )
                    if not result.success:
                        failed = True
                        logger.error("[WebsiteDeploy] %s not queued: %s", domain, result.error)
            except Exception as exc:
                logger.exception("[WebsiteDeploy] %s error: %s", domain, exc)
                failed = True

            # Only ever stamp the RUN time here. The status belongs to the
            # pipeline ('deploy_pending' = queued for the push) and to
            # mark_deploy_pushed ('deployed' = bytes actually landed) — writing
            # 'success' here would claim a deploy that never happened.
            ts = datetime.datetime.now(timezone.utc).isoformat()
            rows = [(key_ts, ts)] + ([(key_st, "failed")] if failed else [])
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    for k, v in rows:
                        cur.execute(
                            """INSERT INTO system_config (key, value, updated_at)
                               VALUES (%s, %s, NOW())
                               ON CONFLICT (key) DO UPDATE
                               SET value = EXCLUDED.value, updated_at = NOW()""",
                            (k, v),
                        )
            except Exception as exc:
                logger.error("[WebsiteDeploy] system_config update failed: %s", exc)

    def _portrait_refinement_worker(self):
        """Process pending portrait refinement jobs queued via unified_tasks.

        Creative & Design — M.U.S.E. Director. Runs every 30s, max_instances=1.
        Picks one pending portrait_refinement task, runs full 3-step pipeline
        (vision → agent consultation → M.U.S.E. synthesis), all via DHQ dispatch.
        User can walk away and return to see status — job persists in unified_tasks.
        """
        from database import get_db_cursor
        import psycopg2.extras

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE unified_tasks SET status = 'in_progress'
                       WHERE id = (
                           SELECT id FROM unified_tasks
                           WHERE task_type = 'portrait_refinement' AND status = 'pending'
                           ORDER BY priority DESC, id ASC
                           LIMIT 1
                           FOR UPDATE SKIP LOCKED
                       )
                       RETURNING id, metadata""",
                )
                row = cur.fetchone()

            if not row:
                return

            task_id = row["id"]
            meta = row["metadata"] or {}
            agent_id = meta.get("agent_id")
            feedback = meta.get("feedback", "")
            history = meta.get("history") or []

            if not agent_id or not feedback:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE unified_tasks SET status='failed', metadata = metadata || %s WHERE id=%s",
                        (psycopg2.extras.Json({"error": "missing agent_id or feedback"}), task_id),
                    )
                return

            try:
                from tools.media_studio.services.portrait_service import refine_identity_prompt

                result = refine_identity_prompt(agent_id, feedback, history=history)

                if "error" in result:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            "UPDATE unified_tasks SET status='failed', metadata = metadata || %s WHERE id=%s",
                            (psycopg2.extras.Json({"error": result["error"]}), task_id),
                        )
                    return

                # Save result into task metadata + mark completed
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """UPDATE unified_tasks
                           SET status = 'completed', completed_at = NOW(),
                               metadata = metadata || %s
                           WHERE id = %s""",
                        (psycopg2.extras.Json({"result": result}), task_id),
                    )
                    # Also persist to portrait_refinement_log
                    cur.execute(
                        "SELECT COALESCE(MAX(round_number),0)+1 AS next_round FROM portrait_refinement_log WHERE agent_id=%s",
                        (agent_id,),
                    )
                    round_num = cur.fetchone()["next_round"]
                    cur.execute(
                        """INSERT INTO portrait_refinement_log
                           (agent_id, round_number, feedback, vision_description, agent_perspective,
                            refined_prompt, explanation)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            agent_id,
                            round_num,
                            feedback,
                            result.get("vision_description", ""),
                            result.get("agent_perspective", ""),
                            result.get("refined_prompt", ""),
                            result.get("explanation", ""),
                        ),
                    )

            except Exception as exc:
                logger.exception("portrait_refinement_worker: task %s failed: %s", task_id, exc)
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE unified_tasks SET status='failed', metadata = metadata || %s WHERE id=%s",
                        (psycopg2.extras.Json({"error": str(exc)}), task_id),
                    )

        except Exception as exc:
            logger.error("portrait_refinement_worker outer error: %s", exc)

    def ab_compare_worker(self):
        """Drain approved cloud A/B comparison runs (#4661). ~30s cadence.

        Claims 'pending_approval' action_benchmark_runs whose linked
        autonomy_approval_queue row has resolved (approved/rejected/expired),
        then dispatches + judges the approved ones. Toggle via
        work:ab_compare_worker:enabled (work_control_service).
        """
        from services.work_control_service import is_enabled

        if not is_enabled("ab_compare_worker", default=True):
            return

        from tools.agent_academy.ab_compare import decide_worker_action
        from database import get_db_cursor
        import json

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT r.id, r.test_config, r.metadata, "
                    "  EXTRACT(EPOCH FROM (NOW() - r.started_at)) AS age, "
                    "  a.status AS approval_status "
                    "FROM action_benchmark_runs r "
                    "LEFT JOIN autonomy_approval_queue a "
                    "  ON a.id = (r.metadata->>'approval_id')::int "
                    "WHERE r.status = 'pending_approval' "
                    "  AND r.test_config->>'type' = 'ab_compare' LIMIT 10"
                )
                pending = cur.fetchall()
        except Exception as e:
            logger.warning("ab_compare_worker fetch failed: %s", e)
            return

        # Reaper: the scan above only ever revisits 'pending_approval' rows, so
        # a run that was claimed ('running') and then orphaned by a mid-flight
        # worker crash/restart would otherwise stay 'running' forever with no
        # path back to a terminal state (#4661 final-review Important fix).
        # Age-gated + scoped to ab_compare so it can't touch the synchronous
        # both-local ab_test path or the older per-agent benchmark runner.
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE action_benchmark_runs SET status='failed', completed_at=NOW(), "
                    "metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb),'{cancelled_reason}', "
                    "%s::jsonb) "
                    "WHERE test_config->>'type' = 'ab_compare' AND status = 'running' "
                    "AND started_at < NOW() - INTERVAL '15 minutes'",
                    (json.dumps("worker_timeout"),),
                )
        except Exception as e:
            logger.warning("ab_compare_worker reaper sweep failed: %s", e)

        for run in pending:
            action = decide_worker_action(run["approval_status"] or "pending", float(run["age"] or 0))
            if action == "skip":
                continue
            run_id = run["id"]
            if action == "cancel":
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE action_benchmark_runs SET status='cancelled', completed_at=NOW(), "
                        "metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb),'{cancelled_reason}', "
                        "%s::jsonb) WHERE id=%s AND status='pending_approval'",
                        (json.dumps(f"approval {run['approval_status']}"), run_id),
                    )
                continue
            # action == "run": idempotent claim — another tick/worker may have grabbed it first
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE action_benchmark_runs SET status='running' "
                    "WHERE id=%s AND status='pending_approval' RETURNING id",
                    (run_id,),
                )
                claimed = cur.fetchone()
            if not claimed:
                continue  # another worker took it
            try:
                self._run_ab_comparison(run_id, run["test_config"])
            except Exception as exc:
                logger.exception("ab_compare_worker: run %s failed: %s", run_id, exc)
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE action_benchmark_runs SET status='failed', completed_at=NOW(), "
                        "metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb),'{cancelled_reason}', "
                        "%s::jsonb) WHERE id=%s",
                        (json.dumps(f"worker exception: {exc}"[:500]), run_id),
                    )

    def _run_ab_comparison(self, run_id, cfg):
        """Dispatch both sides of an approved cloud A/B run, judge locally, complete the run (#4661).

        Integration notes (verified against live code, not assumed):
        - DispatchResult (department_dispatcher.py) has no `total_tokens` field —
          only `prompt_tokens` + `completion_tokens`. Both are stored individually
          (action_benchmark_results.prompt_tokens/completion_tokens) plus their
          sum (total_tokens), so /api/ab-test/run/<id> can report real token
          fidelity instead of dumping the whole total into completion_tokens
          (#4661 final-review fix).
        - `agent_id` on action_benchmark_results is NOT NULL + FK->agents(id).
          DispatchResult.agent_id can be None (contractor/error/queued paths)
          and there is no agents.id=0 row, so a bare `agent_id=0` (as the
          existing synchronous ab_test path uses) would raise a
          ForeignKeyViolation. Fall back to id=2 (A.R.C.H.I.E.) — the same
          "system" placeholder id already used elsewhere in
          department_dispatcher.py (e.g. parent_agent_id=2).
        - dispatch_json() returns Optional[Dict] (already-parsed JSON or
          None on failure) — NOT a DispatchResult-like object. It has no
          .response/.success. Re-serialize the dict so parse_judge_result
          (which expects raw text and does its own robust extraction +
          score clamping) can run unchanged.
        """
        from tools.agent_academy.ab_compare import build_judge_prompt, parse_judge_result
        from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json
        from database import get_db_cursor
        import json

        def run_side(sel, label):
            kwargs = {"model_override": sel["model"]}
            if sel["kind"] == "local":
                kwargs["local_only"] = True
            res = dispatch(
                cfg.get("capability", "benchmark"),
                cfg["prompt"],
                module_id=f"agent_academy:ab_compare:{label}",
                **kwargs,
            )
            provider = sel["provider"] if sel["kind"] == "cloud" else "ollama"
            return res, provider

        res_a, prov_a = run_side(cfg["sel_a"], "a")
        res_b, prov_b = run_side(cfg["sel_b"], "b")

        def insert_result(name, sel, res, provider):
            prompt_tok = getattr(res, "prompt_tokens", 0) or 0
            completion_tok = getattr(res, "completion_tokens", 0) or 0
            total_tok = prompt_tok + completion_tok
            agent_id_val = getattr(res, "agent_id", None) or 2
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO action_benchmark_results (run_id, agent_id, agent_name, model_used, "
                    "provider, duration_ms, prompt_tokens, completion_tokens, total_tokens, success, "
                    "error_message, response_preview, tested_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                    (
                        run_id,
                        agent_id_val,
                        name,
                        sel["model"],
                        provider,
                        getattr(res, "duration_ms", None),
                        prompt_tok,
                        completion_tok,
                        total_tok,
                        bool(getattr(res, "success", False)),
                        getattr(res, "error", None),
                        (getattr(res, "response", "") or "")[:4000],
                    ),
                )

        insert_result("model_a", cfg["sel_a"], res_a, prov_a)
        insert_result("model_b", cfg["sel_b"], res_b, prov_b)

        # local judge (only if both sides succeeded)
        judge = {"score_a": None, "score_b": None, "winner": None, "rationale": "skipped (a side failed)"}
        if getattr(res_a, "success", False) and getattr(res_b, "success", False):
            jp = build_judge_prompt(cfg["prompt"], res_a.response, res_b.response)
            jres = dispatch_json(
                "analyze",
                jp,
                module_id="agent_academy:ab_judge",
                model_override="qwen2.5:7b",
                local_only=True,
            )
            # jres is Optional[Dict] (see docstring) — never a DispatchResult.
            judge = parse_judge_result(json.dumps(jres) if isinstance(jres, dict) else "")
            with get_db_cursor(commit=True) as (conn, cur):
                for name, sc, rk in (
                    ("model_a", judge["score_a"], 1 if judge["winner"] == "a" else 2),
                    ("model_b", judge["score_b"], 1 if judge["winner"] == "b" else 2),
                ):
                    cur.execute(
                        "UPDATE action_benchmark_results SET score=%s, rank=%s " "WHERE run_id=%s AND agent_name=%s",
                        (sc, rk, run_id, name),
                    )

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE action_benchmark_runs SET status='completed', completed_at=NOW(), "
                "metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb),'{judge_result}', %s::jsonb) "
                "WHERE id=%s",
                (json.dumps(judge), run_id),
            )

    def _model_dispatch_worker(self):
        """Model-affinity dispatch queue drainer. Department HQ — all products.

        Runs every 15s, max_instances=1. Routes queued tasks to whichever node
        has the required model warm, minimising VRAM swaps. ADR-004.
        """
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.model_dispatch_service import model_dispatch_worker

            model_dispatch_worker()
        except Exception as exc:
            logger.error("model_dispatch_worker error: %s", exc)

    def _compute_media_analytics(self):
        """Compute hourly analytics snapshots. Also daily at midnight."""
        from datetime import datetime
        from tools.media_studio.services.analytics_service import compute_snapshot

        try:
            count = compute_snapshot(period_type="hourly")
            logger.info(f"[Analytics] Hourly: {count} snapshots")
            if datetime.now(timezone.utc).hour == 0:
                daily_count = compute_snapshot(period_type="daily")
                logger.info(f"[Analytics] Daily: {daily_count} snapshots")
        except Exception as e:
            logger.error(f"[Analytics] Snapshot failed: {e}")

    def _process_agent_emails(self):
        """Process inboxes for all agent Gmail accounts."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT id FROM google_accounts WHERE owner_type = 'agent'")
                accounts = cur.fetchall()
            if not accounts:
                return
            from tools.google_work_suite.services.gmail_service import (
                process_agent_inbox,
            )

            for acc in accounts:
                try:
                    process_agent_inbox(acc["id"])
                except Exception as e:
                    logger.warning(f"Agent email processing failed for account {acc['id']}: {e}")
        except Exception as e:
            logger.error(f"Agent email job failed: {e}")

    def _agent_calendar_drive_tasks(self):
        """Auto-schedule calendar events from tasks for all agent Google accounts."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT id, owner_id FROM google_accounts WHERE owner_type = 'agent'")
                accounts = cur.fetchall()
            if not accounts:
                return
            from tools.google_work_suite.services.calendar_service import (
                auto_schedule_from_tasks,
            )

            for acc in accounts:
                try:
                    auto_schedule_from_tasks(acc["id"], str(acc["owner_id"]))
                except Exception as e:
                    logger.warning(f"Agent calendar task failed for account {acc['id']}: {e}")

            # Daily summary at ~6pm UTC
            from datetime import datetime

            if datetime.now(timezone.utc).hour == 18:
                from tools.google_work_suite.services.drive_service import (
                    generate_daily_summary,
                )

                for acc in accounts:
                    try:
                        generate_daily_summary(acc["id"], str(acc["owner_id"]))
                    except Exception as e:
                        logger.warning(f"Daily summary failed for {acc['id']}: {e}")
        except Exception as e:
            logger.error(f"Agent calendar/drive job failed: {e}")

    def _deduplicate_knowledge(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py deduplicate_knowledge()"""
        pass

    def _index_claude_sessions(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py index_claude_sessions()"""
        pass

    def _update_module_docs(self):
        """Job #30: Update module documentation and agent module awareness (daily)."""
        try:
            from services.module_docs_service import generate_module_docs

            generate_module_docs()
            from services.agent_module_awareness import update_agent_module_awareness

            update_agent_module_awareness()
        except Exception as e:
            logger.error(f"[Module Docs] Error: {e}")

    def _track_git_changes(self):
        """Job #31: Track recent git commits and store in knowledge_base (every 30 min)."""
        try:
            import subprocess

            result = subprocess.run(
                ["git", "log", "--oneline", "-5", "--format=%h %s (%ar)"],
                cwd="/mnt/archie_brain",
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                recent = result.stdout.strip()
                from database import get_db_cursor
                from psycopg2.extras import Json

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO knowledge_base (title, content, category, importance, tags, knowledge_type)
                        VALUES ('Recent Git Commits', %s, 'version_control', 0.6, %s, 'conversation_memory')
                        ON CONFLICT (title) DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                        """,
                        (recent, Json(["git", "commits", "version-control", "auto-generated"])),
                    )
        except Exception as e:
            logger.error(f"[Git Tracker] Error: {e}")

    def stop(self):
        """Remove agent loop jobs from the scheduler."""
        for job_id in [
            "agent_email_queue",
            "agent_scheduled_tasks",
            "agent_reminders",
            "agent_approvals",
            "agent_email_inbox",
            "agent_email_analyze",
            "agent_telegram_notify",
            "agent_email_telegram_notify",
            "agent_hr_tracker",
            "agent_browser_tasks",
            "agent_briefings",
            "agent_anomaly_detection",
            "agent_reports",
            "agent_ethics_monitoring",
            "agent_stale_job_reaper",
            "agent_training_tick",
            "agent_proactive_scan",
            "agent_welfare_recovery",
            "agent_idle_volunteering",
            "agent_performance_rankings",
            "agent_media_generation",
            "media_analytics_snapshot",
            "agent_email_processing",
            "game_world_event_processor",
            "game_market_price_update",
            "agent_calendar_drive",
            "knowledge_deduplication",
            "session_indexer",
            "module_docs_updater",
            "git_change_tracker",
            "agent_code_health_digest",
            "agent_code_health_scan",
            "agent_competitor_scan",
        ]:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        self._running = False
        logger.info("Agent loop stopped")

    @property
    def is_running(self):
        return self._running

    def get_status(self) -> dict:
        """Get current status of all agent loop jobs."""
        jobs = []
        for job_id in [
            "agent_email_queue",
            "agent_scheduled_tasks",
            "agent_reminders",
            "agent_approvals",
            "agent_email_inbox",
            "agent_email_analyze",
            "agent_telegram_notify",
            "agent_email_telegram_notify",
            "agent_browser_tasks",
            "agent_briefings",
            "agent_anomaly_detection",
            "agent_reports",
            "agent_hr_tracker",
            "agent_stale_job_reaper",
            "agent_ethics_monitoring",
            "agent_training_tick",
        ]:
            try:
                job = self.scheduler.get_job(job_id)
                if job:
                    jobs.append(
                        {
                            "id": job.id,
                            "name": job.name,
                            "next_run": (str(job.next_run_time) if job.next_run_time else None),
                        }
                    )
            except Exception:
                pass

        return {
            "running": self._running,
            "jobs": jobs,
            "job_count": len(jobs),
        }

    # ------------------------------------------------------------------
    # Email Queue Processor
    # ------------------------------------------------------------------

    def _keep_embeddings_warm(self):
        """Keep arctic-embed-cpu loaded on every fleet node so it never
        cold-loads (#3525). Runs every 25 min — shorter than the 35m keep_alive
        — pinging each node in the embedding pool with a tiny embed."""
        try:
            from ai_bridge.embedding_service import warm_all_nodes

            results = warm_all_nodes()
            ok = sum(1 for v in results.values() if v == "ok")
            logger.info("[Agent Loop] Embedding keep-warm: %d/%d nodes warm", ok, len(results))
        except Exception as e:
            logger.warning("[Agent Loop] Embedding keep-warm failed: %s", e)

    def _keep_cockpit_model_warm(self):
        """Keep the interactive cockpit conversation model resident on the HUB,
        CPU-only, so A.R.C.H.I.E.'s cockpit chat never cold-loads (#4270).

        NARROW, owner-approved exception (2026-06-21) to the _CPU_TIER_NO_WARMUP
        policy in ollama_model_health (7B models are normally NOT proactively
        warmed to avoid RAM/VRAM crowding). Here we pin ONLY the cockpit's
        conversation model and CPU-ONLY (num_gpu=0): ~5GB of the hub's 128GB RAM,
        ZERO VRAM (the 8GB Quadro stays free for the small GPU warm set + batch).
        This MATCHES the dispatcher's own placement — build_options already places
        qwen2.5:7b on CPU on the hub once the small GPU models are resident
        (insufficient_vram_too_big), so the cockpit dispatch hits this exact warm
        copy with no reload, and is decoupled from GPU-batch contention.

        Runs every 30 min (shorter than the 45m keep_alive). Disable via the
        standard job toggle (id=agent_cockpit_model_keepwarm) if RAM is ever tight.
        """
        import time

        start = time.time()
        model = "qwen2.5:7b"  # fallback; resolved to A.R.C.H.I.E.'s configured model below
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT model FROM agents WHERE name = %s", ("A.R.C.H.I.E.",))
                row = cur.fetchone()
            if row and row.get("model") and ":cloud" not in row["model"]:
                model = row["model"]
        except Exception:
            pass  # fall back to qwen2.5:7b

        try:
            import requests as req

            ollama_host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
            if not ollama_host.startswith("http"):
                ollama_host = f"http://{ollama_host}"
            data = {
                "model": model,
                "prompt": "warm",
                "stream": False,
                # CPU-only — keep ZERO VRAM footprint; matches build_options'
                # CPU placement for this model on the hub so the dispatch reuses
                # this runner (no GPU reload, no VRAM crowding).
                "options": {"num_predict": 1, "num_gpu": 0},
                "keep_alive": "45m",
            }
            # 7B cold-loads into RAM in tens of seconds; give it room like the
            # big-CPU-tier keep-warm (KB #270009). Subsequent cycles are fast.
            resp = req.post(f"{ollama_host}/api/generate", json=data, timeout=600)
            ok = resp.status_code == 200
            logger.info(
                "[Agent Loop] Cockpit model keep-warm: %s %s (%dms)",
                model,
                "warm" if ok else f"FAILED {resp.status_code}",
                int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.warning("[Agent Loop] Cockpit model keep-warm failed: %s", e)

    def _keep_forge_review_model_warm(self):
        """Keep the F.O.R.G.E. code-review model (qwen2.5:7b) GPU-resident on the review node
        (Starship-246 'Defiant', RTX 3070) so reviews don't cold-load.

        2026-06-23 diagnosis: the review 7B unloaded between sporadic F.O.R.G.E. reviews (node
        KEEP_ALIVE=10m, reviews usually >10m apart), so each review cold-loaded the model on the
        Windows node → 280-322s spikes that blew the 240s per-node dispatch cap → fell to the
        weaker freeform path. Warm hits run in 15-30s. This pins the model resident and warms it at
        the SAME num_ctx the reviews use (forge:review_num_ctx, QW-5) so the review reuses this exact
        runner with no reload. Mirrors the owner-approved cockpit keep-warm (#4270) — a direct
        /api/generate ping is the sanctioned exception to ADR-013 for keep-warm only.

        Online-gated + UNDOCK-gated. #5332 NOTE: this docstring claimed the 8PM-6AM
        hardware-rest skip long before the gate existed — the only real gate was
        node-online, so a resting-but-powered ship still got pinged every 4 min.
        The is_starships_undocked() early-return below makes the claim true
        (scheduled rest OR manual force-undock). Runs every 4 min with a 10m
        keep_alive, so even a review that resets keep_alive to ~5m never lapses
        before the next ping. Toggle via the job id `forge_review_model_keepwarm`.
        """
        import time

        start = time.time()
        # #5332: UNDOCKED = leave the ships alone — skip before any node contact.
        try:
            from tools.department_hq.fleet_helpers import is_starships_undocked

            if is_starships_undocked():
                return
        except Exception:
            pass  # fail-open: a predicate error must not stop keep-warm while docked
        review_node_id = "starship_76583490e36955ab"  # Defiant USS-246 (RTX 3070)
        node_label = "Defiant USS-246"
        model = "qwen2.5:7b"
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute(
                    "SELECT mesh_ip, hostname, status, "
                    "EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS hb_age "
                    "FROM remote_nodes WHERE node_id = %s",
                    (review_node_id,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.warning("[Agent Loop] F.O.R.G.E. review keep-warm: node lookup failed: %s", e)
            return
        if not row:
            return
        host = row.get("mesh_ip") or row.get("hostname")
        if row.get("status") != "online" or (row.get("hb_age") or 9999) > 180 or not host:
            logger.info("[Agent Loop] F.O.R.G.E. review keep-warm: %s offline/stale — skip", node_label)
            return

        # Match the review's num_ctx so this warm runner is the exact instance reviews reuse (a
        # different num_ctx is a different Ollama runner = a reload, which would waste the warm-up).
        opts = {"num_predict": 1}
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = %s", ("forge:review_num_ctx",))
                r2 = cur.fetchone()
            nc = int(str((r2 or {}).get("value") or "0").strip() or "0")
            if nc >= 512:
                opts["num_ctx"] = nc
        except Exception:
            pass  # default num_ctx — matches a flag-off review

        try:
            import requests as req

            data = {
                "model": model,
                "prompt": "warm",
                "stream": False,
                # No num_gpu → Ollama fills the RTX 3070 first (the 7B fits in 8GB); GPU-resident = fast.
                "options": opts,
                "keep_alive": "10m",
            }
            resp = req.post(f"http://{host}:11434/api/generate", json=data, timeout=600)
            ok = resp.status_code == 200
            logger.info(
                "[Agent Loop] F.O.R.G.E. review keep-warm: %s on %s %s (%dms)",
                model,
                node_label,
                "warm" if ok else f"FAILED {resp.status_code}",
                int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.warning("[Agent Loop] F.O.R.G.E. review keep-warm failed: %s", e)

    def _keep_cockpit_node_model_warm(self):
        """Keep the interactive cockpit FAST-FRONT model (llama3.2:3b) resident on the
        cockpit's GPU node (Starship-246 'Defiant', RTX 3070) so A.R.C.H.I.E.'s first
        reply never cold-loads.

        The cockpit chat routes its conversational reply to this node with a fast
        GPU-resident model (COCKPIT_CHAT_MODEL, default llama3.2:3b) — PR #2217. But
        cockpit chats are sporadic (usually far apart), so the model unloaded between them
        (the node KEEP_ALIVE lapsed) and each first reply cold-loaded → the 14-34s variance
        the owner saw. This pins it resident. The deepen follow-up's 7B is already covered by
        _keep_forge_review_model_warm on this SAME node, so we warm ONLY the small fast-front
        model here (no second 7B runner → no 8GB-VRAM crowding).

        Warmed CPU-only (num_gpu=0) at the cockpit's default num_ctx so it matches the runner the
        dispatch actually creates on the full-GPU node (build_options CPU-places the 3B when the
        forge 7B holds the GPU — a GPU warm copy would be a different runner the dispatch won't
        reuse). Online-gated + UNDOCK-gated (#5332 — the old "8PM-6AM hardware rest" claim here
        was aspirational; the is_starships_undocked() early-return below makes it real, covering
        scheduled rest AND manual force-undock). Runs every 4 min with a 30m keep_alive — mirrors
        the sibling keep-warms so even a chat that resets keep_alive never lapses before the next
        ping. A direct /api/generate ping is the sanctioned ADR-013 exception
        for keep-warm only. Toggle via the job id `cockpit_node_model_keepwarm`.
        """
        import time

        start = time.time()
        # #5332: UNDOCKED = leave the ships alone — skip before any node contact.
        try:
            from tools.department_hq.fleet_helpers import is_starships_undocked

            if is_starships_undocked():
                return
        except Exception:
            pass  # fail-open: a predicate error must not stop keep-warm while docked
        node_id = "starship_76583490e36955ab"  # Defiant USS-246 (RTX 3070)
        node_label = "Defiant USS-246"
        model = os.getenv("COCKPIT_CHAT_MODEL", "llama3.2:3b")  # matches the cockpit fast-front routing
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute(
                    "SELECT mesh_ip, hostname, status, "
                    "EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS hb_age "
                    "FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.warning("[Agent Loop] Cockpit node keep-warm: node lookup failed: %s", e)
            return
        if not row:
            return
        host = row.get("mesh_ip") or row.get("hostname")
        if row.get("status") != "online" or (row.get("hb_age") or 9999) > 180 or not host:
            logger.info("[Agent Loop] Cockpit node keep-warm: %s offline/stale — skip", node_label)
            return

        try:
            import requests as req

            data = {
                "model": model,
                "prompt": "warm",
                "stream": False,
                # CPU-pin (num_gpu=0): on the contended 8GB card the forge review 7B holds the
                # GPU, so build_options CPU-places the cockpit 3B too — warming it CPU-only here
                # MATCHES the runner the dispatch actually creates. A GPU warm copy is a DIFFERENT
                # Ollama runner the dispatch won't reuse, so it cold-loads anyway (observed: a real
                # cockpit chat = 11.7s despite a fresh GPU keep-warm). CPU also keeps it resident in
                # the node's ample 32GB RAM instead of thrashing against the 7B for VRAM. Mirrors the
                # hub cockpit keep-warm (#4270). No num_ctx → both default, so the runners also match
                # on context.
                "options": {"num_predict": 1, "num_gpu": 0},
                "keep_alive": "30m",
            }
            resp = req.post(f"http://{host}:11434/api/generate", json=data, timeout=600)
            ok = resp.status_code == 200
            logger.info(
                "[Agent Loop] Cockpit node keep-warm: %s on %s %s (%dms)",
                model,
                node_label,
                "warm" if ok else f"FAILED {resp.status_code}",
                int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.warning("[Agent Loop] Cockpit node keep-warm failed: %s", e)

    def _keep_citadel_async_model_warm(self):
        """Win 2 (2026-06-23): keep the documentation model (mistral:7b) warm on Citadel (boston-2,
        31GB RAM, CPU-only) so `documentation` dispatches routed there (CAPABILITY_NODE_AFFINITY) hit
        it warm instead of cold-loading (~60s) on each delegated doc.

        Conservative async offload: docs are low-volume (~55/day) + latency-tolerant, and routing them
        to Citadel keeps doc-gen OFF the Defiant GPU so it can't evict the warm review 7B (#1905).
        Citadel is the DR + watch-products node, so this is CPU-pinned (num_gpu=0, ~5GB of its 25GB
        free) and online-gated — it must never starve the watch products. Mirrors the Defiant review
        keep-warm; a direct /api/generate ping is the sanctioned ADR-013 exception for keep-warm only.
        Toggle via the job id `citadel_async_model_keepwarm`.
        """
        import time

        start = time.time()
        node_id = "outpost_e834ff6949a3d7a6"  # Citadel / boston-2 (CPU, 31GB RAM)
        node_label = "Citadel"
        model = "mistral:7b"
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute(
                    "SELECT mesh_ip, hostname, status, "
                    "EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) AS hb_age "
                    "FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                row = cur.fetchone()
        except Exception as e:
            logger.warning("[Agent Loop] Citadel async keep-warm: node lookup failed: %s", e)
            return
        if not row:
            return
        host = row.get("mesh_ip") or row.get("hostname")
        if row.get("status") != "online" or (row.get("hb_age") or 9999) > 180 or not host:
            logger.info("[Agent Loop] Citadel async keep-warm: %s offline/stale — skip", node_label)
            return
        try:
            import requests as req

            data = {
                "model": model,
                "prompt": "warm",
                "stream": False,
                "options": {"num_predict": 1, "num_gpu": 0},  # CPU-only (Citadel has no GPU)
                "keep_alive": "30m",
            }
            resp = req.post(f"http://{host}:11434/api/generate", json=data, timeout=600)
            logger.info(
                "[Agent Loop] Citadel async keep-warm: %s on %s %s (%dms)",
                model,
                node_label,
                "warm" if resp.status_code == 200 else f"FAILED {resp.status_code}",
                int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.warning("[Agent Loop] Citadel async keep-warm failed: %s", e)

    def _keep_cluster_models_warm(self):
        """Win 1 (2026-06-23): keep the hot, cold-loading HUB 7Bs resident so their dispatches hit
        them warm instead of paying the cold-load tax (task_execution_log 7d: 30-56s averages,
        10-18min max tails). Generalizes the cockpit (#4270) + Defiant-review (#1905) keep-warm to
        the data-identified hot models.

        Placement is decided per cycle by model_service.hub_gpu_placement (#5276): GPU when the
        dual-card fit budget allows (TITAN X 12GB + Quadro M4000 8GB since 2026-07-25), CPU-pinned
        when VRAM is tight or ComfyUI is awake — warmth is preserved either way. The registry used
        to hardcode num_gpu=0 (written for the 8GB-only hub); firing every 4 min with a 30m
        keep-alive, that pin overrode every correct placement and kept both 7Bs on CPU while 20GB
        of VRAM sat empty — the #5276 defect.

        MIGRATION (#5328): Ollama does NOT reload a LIVE runner when a warm request merely omits
        num_gpu (measured: three gpu-eligible cycles left qwen2.5:7b at 100% CPU — its dispatch
        volume never lets the runner expire), while a FRESH load auto-places on GPU. So when the
        placement says GPU but the model is resident holding zero VRAM, this cycle unloads it
        first (keep_alive=0 queues behind in-flight work) and the warm below cold-starts it onto
        the card.

        Runs every 4 min — shorter than the ~5m keep_alive a dispatch resets the model to — with a 30m
        keep_alive, so the model never unloads between sporadic dispatches. The Defiant GPU review-7B
        is handled by forge_review_model_keepwarm; here we cover the hub 7Bs (incl. qwen2.5:7b, whose
        14k dispatches/wk the cockpit's 30m interval is too slow to keep warm). Toggle the whole job
        via id=cluster_model_keepwarm.
        """
        import time

        import requests as req

        # 7d volume: qwen2.5:7b 14k @33s, mistral:7b 7.9k @43s, qwen25-classify 2.4k @24s. All
        # confirmed present on the hub Ollama. Coordinator slot is config-driven
        # (services.coordinator_lane) so a Phase 3 model swap keeps keep-warm in sync without a
        # code change — fail-open to the "qwen25-classify" default on any DB/read error. (The
        # classify model carries num_gpu=0 in its MODELFILE, so an empty placement fragment still
        # leaves it on CPU — intended.)
        from services.coordinator_lane import get_coordinator_model

        registry = [
            "qwen2.5:7b",
            "mistral:7b",
            get_coordinator_model(),
        ]
        ollama_host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
        if not ollama_host.startswith("http"):
            ollama_host = f"http://{ollama_host}"
        for model in registry:
            start = time.time()
            try:
                options = {"num_predict": 1}
                try:
                    from services.model_service import get_model_service, hub_gpu_placement

                    placement = hub_gpu_placement(model)
                    options.update(placement)
                    if not placement:
                        # GPU-bound. A live CPU-pinned runner will NOT move on an
                        # option-omitting warm request (#5328) — unload it so the
                        # warm below fresh-loads onto the card.
                        svc = get_model_service()
                        if svc.resident_vram_gb(model) == 0.0:
                            logger.info(
                                "[Agent Loop] Cluster keep-warm: %s CPU-stranded while GPU-eligible — unloading to migrate",
                                model,
                            )
                            svc.unload_model(model)
                except Exception as pe:
                    # Placement unknowable — keep the historical CPU pin so the warm
                    # request can never evict or overfill a card it cannot measure.
                    options["num_gpu"] = 0
                    logger.warning(
                        "[Agent Loop] Cluster keep-warm: placement check failed for %s (%s) — CPU pin",
                        model,
                        pe,
                    )
                data = {
                    "model": model,
                    "prompt": "warm",
                    "stream": False,
                    "options": options,
                    "keep_alive": "30m",
                }
                resp = req.post(f"{ollama_host}/api/generate", json=data, timeout=600)
                logger.info(
                    "[Agent Loop] Cluster keep-warm: %s %s (%dms)",
                    model,
                    "warm" if resp.status_code == 200 else f"FAILED {resp.status_code}",
                    int((time.time() - start) * 1000),
                )
            except Exception as e:
                logger.warning("[Agent Loop] Cluster keep-warm %s failed: %s", model, e)

    def _forge_review_path_observer(self):
        """ST-4 observer (2026-06-23): catch a SILENT regression of F.O.R.G.E. review quality and
        alert a human via the director->A.R.C.H.I.E. inbox (F.O.R.G.E. can't call telegram directly —
        unified-voice guard). Two checks, runs every 6h, 12h cooldown so a persistent regression
        alerts once rather than every run:

        (A) CONFIG GUARD (deterministic, primary): a critical anti-hallucination guard flag was turned
            OFF — the realistic 'someone flipped a flag and forgot' regression (forge_settings_snapshot).
        (B) RATIO GUARD (secondary, conservative): the structured(json) review ratio CRASHED to near
            zero. The raw ratio is noisy (~20-55% — many legit reviews lack the [review-meta] line), so
            this only trips on a near-zero crash with a real sample (likely a JSON-parse break).
        """
        findings = []
        # (A) deterministic config guard
        try:
            from tools.repair_bay.services.pr_diff_analyzer import forge_settings_snapshot

            snap = forge_settings_snapshot()
            critical = [
                "forge:structured_review_enabled",
                "forge:freeform_gate_enabled",
                "forge:evidence_verification_enabled",
                "forge:self_refute_failclosed_enabled",
            ]
            off = [k for k in critical if not snap.get(k)]
            if not snap.get("forge:review_num_ctx"):  # 0/None == QW-5 window off
                off.append("forge:review_num_ctx(off)")
            if off:
                findings.append("guard flags OFF: " + ", ".join(off))
        except Exception as e:
            logger.warning("[Agent Loop] F.O.R.G.E. observer: config check failed: %s", e)

        # (B) conservative ratio-crash guard
        try:
            from tools.repair_bay.services.pr_review_service import get_forge_review_metrics

            m = get_forge_review_metrics(days=2)
            total = int(m.get("total") or 0)
            ratio = m.get("structured_ratio")
            if total >= 15 and ratio is not None and ratio < 0.05:
                findings.append(
                    f"structured(json) review ratio crashed to {ratio:.0%} over 2d "
                    f"({total} reviews) — likely a JSON-parse break"
                )
        except Exception as e:
            logger.warning("[Agent Loop] F.O.R.G.E. observer: ratio check failed: %s", e)

        if not findings:
            return  # healthy

        # 12h cooldown via platform_settings (PK on key)
        from datetime import datetime, timedelta

        from database import get_db_cursor
        from services.time_utils import now_utc

        try:
            with get_db_cursor(commit=False) as (_c, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key=%s", ("forge:path_observer:last_alert_at",))
                r = cur.fetchone()
            if r and r.get("value"):
                try:
                    if (now_utc() - datetime.fromisoformat(r["value"])) < timedelta(hours=12):
                        return  # within cooldown
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

        msg = (
            "F.O.R.G.E. review-quality regression detected: "
            + "; ".join(findings)
            + ". Check the forge:* flags (forge_settings_snapshot) and the structured/gated "
            "review path (ST-1/ST-4)."
        )
        try:
            from services.director_report_service import submit_via_inbox

            submit_via_inbox(
                category="forge_health",
                title="F.O.R.G.E. review-quality regression",
                message=msg,
                source_agent="F.O.R.G.E.",
                severity="warning",
                department="Engineering & Technology",
            )
            logger.warning("[Agent Loop] F.O.R.G.E. path observer ALERT: %s", msg)
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute(
                    "INSERT INTO platform_settings (key, value, value_type, updated_at) "
                    "VALUES (%s, %s, 'string', %s) "
                    "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                    ("forge:path_observer:last_alert_at", now_utc().isoformat(), now_utc()),
                )
        except Exception as e:
            logger.warning("[Agent Loop] F.O.R.G.E. path observer alert failed: %s", e)

    def _run_benchmark_producer(self):
        """P2-PRODUCER (#381): off-peak benchmark cycle that generates correctness-graded data for
        right-sizing. Gated by platform_settings benchmark_producer_enabled (default OFF) — it no-ops
        when disabled, so this stays dormant until you turn it on. Sovereign (local_only in the cycle)."""
        try:
            from services.benchmark_producer import scheduled_benchmark_cycle

            result = scheduled_benchmark_cycle()
            if not result.get("skipped_disabled"):
                logger.info("[AgentLoop] benchmark producer cycle: %s", result)
        except Exception as exc:
            logger.error("[AgentLoop] benchmark producer failed: %s", exc)

    def _run_model_rightsizing_proposer(self):
        """P2-C part 2 (#381): nightly proposer — turns correctness-graded right-sizing proposals into
        Tier-2 approvals (Telegram). NEVER auto-applies; the owner approves each, then the approval
        executor (_execute_approved_action, action_type='model_rightsizing') swaps the model. No-op when
        there is no graded benchmark data yet (propose_model_rightsizing returns [])."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.agent_academy.services.benchmark_service import propose_model_rightsizing

            proposals = propose_model_rightsizing(quality_tolerance=0.15, days=30, min_samples=5)
            submitted = skipped = 0
            for p in proposals:
                reason = (
                    f"Right-size {p['agent_name']} ({p['category']}): "
                    f"{p['old_model']} → {p['new_model']} "
                    f"(correctness {p['new_avg_correctness']} vs best {p['best_avg_correctness']}, "
                    f"{p.get('new_avg_time_ms')}ms, n={p['samples']})"
                )
                aid = request_approval(
                    action_type="model_rightsizing",
                    action_data={
                        "agent_id": p["agent_id"],
                        "agent_name": p["agent_name"],
                        "category": p["category"],
                        "old_model": p["old_model"],
                        "new_model": p["new_model"],
                        "new_avg_correctness": p["new_avg_correctness"],
                        "best_avg_correctness": p["best_avg_correctness"],
                        "new_avg_time_ms": p.get("new_avg_time_ms"),
                        "samples": p["samples"],
                    },
                    reason=reason,
                    requested_by="model_rightsizing_proposer",
                    priority=5,
                    tier=2,
                )
                if aid:
                    submitted += 1
                else:
                    skipped += 1  # already a pending swap for this agent, or validation
            if proposals:
                logger.info(
                    "[AgentLoop] model right-sizing proposer: %d proposed, %d queued, %d skipped",
                    len(proposals),
                    submitted,
                    skipped,
                )
        except Exception as exc:
            logger.error("[AgentLoop] model right-sizing proposer failed: %s", exc)

    def _stalwart_queue_monitor(self):
        """Every-30-min outbound-mail delivery-failure monitor (#4035).

        Flags Stalwart outbound messages that are failing delivery (high retry /
        aged / failed status) or a large backlog, and alerts via
        system_notifications + Telegram — deduped, only when the failing/backlog
        state changes (mirrors vigil_infra_heartbeat's _last_down_set). Fail-safe:
        never raises; if Stalwart is unreachable the health check returns
        severity='unknown' and no alert fires.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.email_manager.stalwart_service import check_outbound_queue_health

            result = check_outbound_queue_health()
            severity = result.get("severity", "unknown")
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="stalwart_queue_monitor",
                items_processed=result.get("total", 0) or 0,
                items_failed=result.get("failing_count", 0) or 0,
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "total": result.get("total"),
                    "failing_count": result.get("failing_count", 0),
                    "reasons": result.get("reasons", []),
                    "error": result.get("error"),
                },
            )

            # Dedup: record the alert state EVERY run, but only NOTIFY
            # (system_notifications + Telegram) when the failing/backlog state
            # CHANGES — so a persistent backlog does not spam a fresh notification
            # row + Telegram every 30-min tick. A recovery to 'ok' resets the key,
            # so a later re-failure re-alerts.
            alert_key = result.get("alert_key")
            state_changed = alert_key != getattr(self, "_last_stalwart_alert_key", None)
            self._last_stalwart_alert_key = alert_key

            if severity not in ("warning", "error") or not state_changed:
                return

            body_lines = [f"Stalwart outbound queue: {severity.upper()}"]
            body_lines.extend(result.get("reasons", []) or [])
            for f in (result.get("failing") or [])[:8]:
                body_lines.append(
                    f"  • msg {f.get('id')} → {f.get('domain')} "
                    f"(retry {f.get('retry')}, {f.get('age_h')}h, {f.get('status')})"
                )
            body = "\n".join(body_lines)

            # system_notifications row — surfaces in platform UI
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO system_notifications
                      (type, title, message, source, priority, source_icon,
                       related_action, visibility, target_user_id, is_read,
                       metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                    """,
                    (
                        "alert" if severity == "error" else "warning",
                        f"Mail — outbound queue {severity}",
                        body,
                        "stalwart",
                        "high" if severity == "error" else "normal",
                        "📧",
                        "/tools/email-manager",
                        "all",
                        None,
                        psycopg2.extras.Json(
                            {
                                "total": result.get("total"),
                                "failing_count": result.get("failing_count", 0),
                            }
                        ),
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as notify_err:
                logger.warning(
                    "Stalwart queue monitor: system_notifications insert failed: %s",
                    notify_err,
                )

            # Telegram — reached only on a state change (deduped at the top).
            try:
                self._send_telegram(body)
            except Exception as tg_err:
                logger.warning("Stalwart queue monitor: Telegram dispatch failed: %s", tg_err)

        except Exception as e:
            logger.warning("[Agent Loop] Stalwart queue monitor failed: %s", e)

    def _process_email_queue(self):
        """Process pending emails from the email_queue table."""
        start = time.time()
        processed = 0
        failed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check if enabled
            if not self._is_enabled(cur, "email_queue_enabled"):
                cur.close()
                conn.close()
                return

            # Get config
            config = self._get_config(cur, "email_queue_enabled")
            batch_size = config.get("batch_size", 10)

            # Fetch pending emails that are due
            cur.execute(
                """
                SELECT id, template_id, recipient, recipient_name, subject,
                       body_html, variables, priority, attempts, max_attempts, metadata
                FROM email_queue
                WHERE status = 'pending'
                  AND (scheduled_for IS NULL OR scheduled_for <= NOW())
                  AND attempts < max_attempts
                ORDER BY priority ASC, scheduled_for ASC
                LIMIT %s
                """,
                (batch_size,),
            )
            emails = cur.fetchall()

            if not emails:
                cur.close()
                conn.close()
                return

            # Try Google Work Suite first, fall back to SMTP
            gws_account_id = None
            try:
                cur.execute(
                    "SELECT id FROM google_accounts WHERE owner_type = 'agent' AND permission_level = 'full' ORDER BY created_at LIMIT 1"
                )
                gws_row = cur.fetchone()
                if gws_row:
                    gws_account_id = gws_row["id"]
                    logger.debug("Email queue: using GWS account %s", gws_account_id)
            except Exception as e:
                logger.debug("Email queue: GWS account lookup failed: %s", e)

            smtp_settings = None
            if not gws_account_id:
                cur.execute("SELECT * FROM email_settings WHERE is_default = true AND is_active = true")
                smtp_settings = cur.fetchone()

                if not smtp_settings:
                    logger.warning("Agent loop: No GWS account or SMTP settings, skipping email queue")
                    cur.close()
                    conn.close()
                    return

            for email in emails:
                try:
                    # Mark as processing
                    cur.execute(
                        "UPDATE email_queue SET status = 'processing', attempts = attempts + 1 WHERE id = %s",
                        (email["id"],),
                    )
                    conn.commit()

                    # Resolve template if needed
                    subject = email["subject"]
                    body_html = email["body_html"]
                    variables = email["variables"] or {}

                    if email["template_id"] and (not subject or not body_html):
                        cur.execute(
                            "SELECT subject, body_html, body_text FROM email_templates WHERE id = %s",
                            (email["template_id"],),
                        )
                        template = cur.fetchone()
                        if template:
                            subject = subject or template["subject"]
                            body_html = body_html or template["body_html"]

                    # Simple variable substitution
                    if variables:
                        for key, val in variables.items():
                            subject = subject.replace(f"{{{{{key}}}}}", str(val)) if subject else subject
                            body_html = body_html.replace(f"{{{{{key}}}}}", str(val)) if body_html else body_html

                    # Send via GWS Gmail API (preferred) or SMTP fallback
                    if gws_account_id:
                        from tools.google_work_suite.services.gmail_service import (
                            send_email as gws_send_email,
                        )

                        gws_send_email(
                            gws_account_id,
                            email["recipient"],
                            subject or "(no subject)",
                            body_html or "",
                        )
                    else:
                        self._send_smtp(smtp_settings, email["recipient"], subject, body_html)

                    # Log success
                    cur.execute(
                        "UPDATE email_queue SET status = 'sent', processed_at = NOW() WHERE id = %s",
                        (email["id"],),
                    )
                    cur.execute(
                        """
                        INSERT INTO email_logs
                        (template_id, recipient, recipient_name, subject, body_preview, status, metadata, sent_at, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'sent', %s, NOW(), NOW())
                        """,
                        (
                            email["template_id"],
                            email["recipient"],
                            email["recipient_name"],
                            subject,
                            (body_html or "")[:500],
                            json.dumps(email["metadata"] or {}),
                        ),
                    )
                    conn.commit()
                    processed += 1

                except Exception as e:
                    logger.error(f"Failed to send email #{email['id']}: {e}")
                    cur.execute(
                        "UPDATE email_queue SET status = 'failed', error_message = %s WHERE id = %s",
                        (str(e)[:500], email["id"]),
                    )
                    conn.commit()
                    failed += 1

            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Email queue processing error: {e}")
            failed += 1

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or failed > 0:
            self._log_cycle("email_queue", processed, failed, duration_ms)
            logger.info(f"Email queue: {processed} sent, {failed} failed ({duration_ms}ms)")

    def _send_smtp(self, smtp_settings: dict, recipient: str, subject: str, body_html: str):
        """Send a single email via SMTP. Reuses logic from email_manager."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject or "(no subject)"
        msg["To"] = recipient

        from_name = smtp_settings.get("from_name")
        from_email = smtp_settings["from_email"]
        msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email

        if smtp_settings.get("reply_to"):
            msg["Reply-To"] = smtp_settings["reply_to"]

        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        encryption = smtp_settings.get("encryption", "tls")
        host = smtp_settings["smtp_host"]
        port = smtp_settings["smtp_port"]

        if encryption == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            if encryption == "tls":
                server.starttls()

        try:
            user = smtp_settings.get("smtp_user")
            password = smtp_settings.get("smtp_password_encrypted")
            if user and password:
                server.login(user, password)

            server.sendmail(from_email, recipient, msg.as_string())
        finally:
            server.quit()

    # ------------------------------------------------------------------
    # Scheduled Task Processor
    # ------------------------------------------------------------------

    def _process_scheduled_tasks(self):
        """Execute due scheduled tasks via get_due_scheduled_tasks() PL/pgSQL."""
        start = time.time()
        processed = 0
        failed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if not self._is_enabled(cur, "scheduled_tasks_enabled"):
                cur.close()
                conn.close()
                return

            # Call existing PL/pgSQL function
            cur.execute("SELECT * FROM get_due_scheduled_tasks()")
            tasks = cur.fetchall()

            for task in tasks:
                try:
                    self._execute_scheduled_task(cur, conn, task)
                    processed += 1
                except Exception as e:
                    logger.error(f"Failed to execute scheduled task #{task['id']} ({task['name']}): {e}")
                    cur.execute(
                        """
                        UPDATE scheduled_tasks
                        SET status = 'failed', error_message = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (str(e)[:500], task["id"]),
                    )
                    conn.commit()
                    failed += 1

            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Scheduled tasks processing error: {e}")
            failed += 1

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or failed > 0:
            self._log_cycle("scheduled_tasks", processed, failed, duration_ms)
            logger.info(f"Scheduled tasks: {processed} executed, {failed} failed ({duration_ms}ms)")

    def _execute_scheduled_task(self, cur, conn, task: dict):
        """Dispatch a scheduled task by its task_type."""
        task_type = task["task_type"]
        config = task.get("action_config") or {}

        if task_type == "email":
            # Queue the email for the email processor
            cur.execute(
                """
                INSERT INTO email_queue (recipient, subject, body_html, variables, scheduled_for, priority, metadata)
                VALUES (%s, %s, %s, %s, NOW(), 3, %s)
                """,
                (
                    config.get("recipient", ""),
                    config.get("subject", "Scheduled Email"),
                    config.get("body_html", ""),
                    json.dumps(config.get("variables", {})),
                    json.dumps({"source": "scheduled_task", "task_id": task["id"]}),
                ),
            )

        elif task_type == "reminder":
            # Create a notification
            self._create_notification(
                cur,
                notification_type="reminder",
                title=config.get("title", task["name"]),
                message=config.get("message", f"Reminder: {task['name']}"),
                source="agent_loop",
                priority=config.get("priority", "normal"),
            )

        elif task_type == "webhook":
            # Submit to approval queue for external webhooks
            request_approval(
                action_type="external_webhook",
                action_data=config,
                reason=f"Scheduled webhook task: {task['name']}",
                requested_by="scheduled_tasks",
            )

        elif task_type == "notification":
            self._create_notification(
                cur,
                notification_type=config.get("type", "info"),
                title=config.get("title", task["name"]),
                message=config.get("message", task["name"]),
                source="scheduled_task",
                priority=config.get("priority", "normal"),
            )

        else:
            logger.warning(f"Unknown scheduled task type: {task_type} (task #{task['id']})")

        # Mark task complete
        cur.execute(
            """
            UPDATE scheduled_tasks
            SET status = 'completed', executed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (task["id"],),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Reminder Processor
    # ------------------------------------------------------------------

    def _process_reminders(self):
        """Process due reminders via get_due_reminders() PL/pgSQL."""
        start = time.time()
        processed = 0
        failed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if not self._is_enabled(cur, "reminders_enabled"):
                cur.close()
                conn.close()
                return

            # Call existing PL/pgSQL function
            cur.execute("SELECT * FROM get_due_reminders()")
            reminders = cur.fetchall()

            for reminder in reminders:
                try:
                    # Create notification for the reminder
                    self._create_notification(
                        cur,
                        notification_type="reminder",
                        title=reminder.get("title", "Reminder"),
                        message=reminder.get("message", "You have a reminder"),
                        source="agent_loop",
                        priority="normal",
                        related_action=json.dumps(
                            {
                                "reminder_id": reminder["id"],
                                "reminder_type": reminder.get("reminder_type"),
                                "related_type": reminder.get("related_type"),
                                "related_id": reminder.get("related_id"),
                            }
                        ),
                    )

                    # Mark reminder as sent
                    cur.execute(
                        "UPDATE reminders SET status = 'sent', sent_at = NOW() WHERE id = %s",
                        (reminder["id"],),
                    )
                    conn.commit()
                    processed += 1

                except Exception as e:
                    logger.error(f"Failed to process reminder #{reminder['id']}: {e}")
                    failed += 1

            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Reminders processing error: {e}")
            failed += 1

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or failed > 0:
            self._log_cycle("reminders", processed, failed, duration_ms)
            logger.info(f"Reminders: {processed} notified, {failed} failed ({duration_ms}ms)")

    # ------------------------------------------------------------------
    # Email Inbox Check (Phase 2)
    # ------------------------------------------------------------------

    def _check_email_inbox(self):
        """Check IMAP inboxes for new emails via EmailIntelligence."""
        start = time.time()
        try:
            from tools.google_work_suite.services.email_intelligence import EmailIntelligence

            ei = EmailIntelligence()
            result = ei.check_inbox()

            fetched = result.get("fetched", 0)
            analyzed = result.get("analyzed", 0)
            errors = result.get("errors", [])

            if fetched > 0 or errors:
                duration_ms = int((time.time() - start) * 1000)
                self._log_cycle(
                    "email_inbox",
                    fetched,
                    len(errors),
                    duration_ms,
                    details={
                        "analyzed": analyzed,
                        "settings_checked": result.get("settings_checked", 0),
                    },
                )
                logger.info(f"Email inbox: {fetched} fetched, {analyzed} analyzed ({duration_ms}ms)")

                # Create per-user notifications for new emails
                if fetched > 0:
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    # Get distinct account owners who received new mail
                    cur.execute(
                        """SELECT DISTINCT eis.user_id, COUNT(*) as cnt
                        FROM email_inbox e
                        JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
                        WHERE e.created_at > NOW() - INTERVAL '10 minutes'
                        GROUP BY eis.user_id"""
                    )
                    user_counts = cur.fetchall()
                    for uc in user_counts:
                        self._create_notification(
                            cur,
                            notification_type="info",
                            title="New Emails",
                            message=f"{uc['cnt']} new email(s) received",
                            source="email_intelligence",
                            visibility="user",
                            target_user_id=uc["user_id"],
                        )
                    conn.commit()
                    cur.close()
                    conn.close()

        except Exception as e:
            logger.error(f"Email inbox check error: {e}")
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("email_inbox", 0, 1, duration_ms, error_message=str(e))

    # ------------------------------------------------------------------
    # Email Auto-Analysis (background batch)
    # ------------------------------------------------------------------

    def _auto_analyze_emails(self):
        """Auto-analyze unanalyzed emails in background (3 per batch, GPU-safe)."""
        start = time.time()
        cur = None
        conn = None
        try:
            from tools.google_work_suite.services.email_intelligence import EmailIntelligence

            ei = EmailIntelligence()
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id FROM email_inbox
                WHERE ai_analyzed_at IS NULL AND is_archived = FALSE
                ORDER BY received_at DESC LIMIT 3
            """
            )
            rows = cur.fetchall()
            if not rows:
                return

            analyzed = 0
            for row in rows:
                try:
                    ei.analyze_email(row["id"])
                    analyzed += 1
                    time.sleep(1)  # GPU safety delay for Quadro M4000
                except Exception as e:
                    logger.error(f"Auto-analyze email {row['id']} failed: {e}")
                    break  # Stop batch on error (GPU may be overloaded)

            duration_ms = int((time.time() - start) * 1000)
            if analyzed > 0:
                log_governance_event(
                    "email_auto_analyze",
                    "execute",
                    "success",
                    {"analyzed": analyzed, "remaining": len(rows) - analyzed},
                )
                self._log_cycle("email_auto_analyze", analyzed, 0, duration_ms)
                logger.info(f"Auto-analyzed {analyzed} emails")
        except Exception as e:
            logger.error(f"Auto-analyze job failed: {e}")
            self._log_cycle("email_auto_analyze", 0, 1, 0, error_message=str(e))
        finally:
            try:
                if cur:
                    cur.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Telegram Notification Forwarding (Phase 3)
    # ------------------------------------------------------------------

    def _forward_notifications_to_telegram(self):
        """Forward unread notifications to Telegram via the gateway."""
        start = time.time()
        try:
            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if not gateway or not gateway.is_running:
                return
            forwarded = gateway.forward_notifications()
            duration_ms = int((time.time() - start) * 1000)
            count = forwarded if isinstance(forwarded, int) else 0
            if count > 0:
                self._log_cycle("telegram_notifications", count, 0, duration_ms)
        except Exception as e:
            logger.error(f"Telegram notification forwarding error: {e}")
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("telegram_notifications", 0, 1, duration_ms, error_message=str(e))

    # ------------------------------------------------------------------
    # Browser Task Processor (Phase 4)
    # ------------------------------------------------------------------

    def _process_browser_tasks(self):
        """Process pending browser automation tasks."""
        start = time.time()
        processed = 0
        failed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get pending tasks that are due
            cur.execute(
                """
                SELECT id FROM browser_tasks
                WHERE status = 'pending'
                  AND (next_run_at IS NULL OR next_run_at <= NOW())
                ORDER BY priority ASC, created_at ASC
                LIMIT 5
                """
            )
            tasks = cur.fetchall()
            cur.close()
            conn.close()

            if not tasks:
                return

            from browser_automation import BrowserAutomation

            ba = BrowserAutomation()

            for task in tasks:
                try:
                    result = ba.execute_task(task["id"])
                    if result.get("error"):
                        failed += 1
                    else:
                        processed += 1
                except Exception as e:
                    logger.error(f"Browser task #{task['id']} error: {e}")
                    failed += 1

        except Exception as e:
            logger.error(f"Browser tasks processing error: {e}")
            failed += 1

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or failed > 0:
            self._log_cycle("browser_tasks", processed, failed, duration_ms)
            logger.info(f"Browser tasks: {processed} completed, {failed} failed ({duration_ms}ms)")

    # ------------------------------------------------------------------
    # Proactive Intelligence (Phase 5)
    # ------------------------------------------------------------------

    def _generate_briefings(self):
        """Generate any due briefings."""
        try:
            from proactive_intelligence import BriefingGenerator

            bg = BriefingGenerator()
            count = bg.generate_due_briefings()
            if count > 0:
                logger.info(f"Generated {count} briefing(s)")
                self._log_cycle("briefings", count, 0, 0)
        except Exception as e:
            logger.error(f"Briefing generation error: {e}")

    def _check_anomalies(self):
        """Run anomaly detection checks."""
        start = time.time()
        try:
            from proactive_intelligence import AnomalyDetector

            detector = AnomalyDetector()
            result = detector.check_all_rules()
            duration_ms = int((time.time() - start) * 1000)

            if result.get("triggered", 0) > 0:
                self._log_cycle(
                    "anomaly_detection",
                    result.get("checked", 0),
                    0,
                    duration_ms,
                    details=result,
                )
                logger.info(
                    f"Anomaly detection: {result['checked']} checked, {result['triggered']} triggered ({duration_ms}ms)"
                )
        except Exception as e:
            logger.error(f"Anomaly detection error: {e}")

    def _generate_reports(self):
        """Generate any due scheduled reports."""
        try:
            from proactive_intelligence import ReportEngine

            re = ReportEngine()
            count = re.generate_due_reports()
            if count > 0:
                logger.info(f"Generated {count} report(s)")
                self._log_cycle("reports", count, 0, 0)
        except Exception as e:
            logger.error(f"Report generation error: {e}")

    # ------------------------------------------------------------------
    # Email Telegram Notifications (Phase 2 - Email Manager)
    # ------------------------------------------------------------------

    def _notify_email_telegram(self):
        """Send Telegram notifications for newly analyzed emails."""
        start = time.time()
        gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
        if not gateway or not gateway.is_running:
            return
        cur = None
        conn = None
        notified = 0
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get authorized Telegram users with email prefs
            cur.execute(
                """
                SELECT tu.telegram_id, tu.id as tg_user_id,
                       COALESCE(tep.notify_urgent, TRUE) as notify_urgent,
                       COALESCE(tep.notify_action_required, TRUE) as notify_action_required,
                       COALESCE(tep.digest_enabled, TRUE) as digest_enabled,
                       COALESCE(tep.digest_interval_minutes, 60) as digest_interval,
                       tep.last_digest_at
                FROM telegram_users tu
                LEFT JOIN telegram_email_prefs tep ON tu.id = tep.telegram_user_id
                WHERE tu.is_authorized = TRUE
            """
            )
            users = cur.fetchall()
            if not users:
                return

            for user in users:
                # --- Instant notifications for urgent/action_required ---
                categories_instant = []
                if user["notify_urgent"]:
                    categories_instant.append("urgent")
                if user["notify_action_required"]:
                    categories_instant.append("action_required")

                if categories_instant:
                    placeholders = ",".join(["%s"] * len(categories_instant))
                    cur.execute(
                        f"""
                        SELECT id, from_name, from_address, subject, ai_category, ai_summary, ai_priority
                        FROM email_inbox
                        WHERE ai_category IN ({placeholders})
                        AND ai_analyzed_at IS NOT NULL
                        AND telegram_notified_at IS NULL
                        AND is_archived = FALSE
                        ORDER BY received_at DESC LIMIT 5
                    """,
                        categories_instant,
                    )
                    urgent_emails = cur.fetchall()

                    for email in urgent_emails:
                        self._send_email_telegram_notification(gateway, user["telegram_id"], email)
                        cur.execute(
                            "UPDATE email_inbox SET telegram_notified_at = NOW() WHERE id = %s",
                            (email["id"],),
                        )
                        notified += 1
                    conn.commit()

                # --- Digest for non-urgent emails ---
                if user["digest_enabled"]:
                    last_digest = user.get("last_digest_at")
                    interval = user.get("digest_interval", 60)
                    if last_digest:
                        from datetime import timedelta

                        if datetime.now() - last_digest < timedelta(minutes=interval):
                            continue  # Not time for digest yet

                    cur.execute(
                        """
                        SELECT id, from_name, from_address, subject, ai_category, ai_summary
                        FROM email_inbox
                        WHERE ai_analyzed_at IS NOT NULL
                        AND telegram_notified_at IS NULL
                        AND ai_category NOT IN ('urgent', 'action_required')
                        AND is_archived = FALSE
                        ORDER BY received_at DESC LIMIT 20
                    """
                    )
                    digest_emails = cur.fetchall()

                    if digest_emails:
                        self._send_email_telegram_digest(gateway, user["telegram_id"], digest_emails)
                        notified += len(digest_emails)
                        ids = [e["id"] for e in digest_emails]
                        id_placeholders = ",".join(["%s"] * len(ids))
                        cur.execute(
                            f"UPDATE email_inbox SET telegram_notified_at = NOW() WHERE id IN ({id_placeholders})",
                            ids,
                        )

                        # Update last_digest_at
                        cur.execute(
                            """
                            INSERT INTO telegram_email_prefs (telegram_user_id, last_digest_at, created_at, updated_at)
                            VALUES (%s, NOW(), NOW(), NOW())
                            ON CONFLICT ON CONSTRAINT uq_tep_telegram_user
                            DO UPDATE SET last_digest_at = NOW(), updated_at = NOW()
                        """,
                            (user["tg_user_id"],),
                        )
                        conn.commit()

        except Exception as e:
            logger.error(f"Email Telegram notify failed: {e}")
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("email_telegram_notify", 0, 1, duration_ms, error_message=str(e))
        else:
            duration_ms = int((time.time() - start) * 1000)
            if notified > 0:
                self._log_cycle("email_telegram_notify", notified, 0, duration_ms)
        finally:
            try:
                if cur:
                    cur.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    def _send_email_telegram_notification(self, gateway, telegram_id, email):
        """Send instant Telegram notification for a single email."""
        try:
            import asyncio
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            category_emoji = {
                "urgent": "\U0001f6a8",
                "action_required": "\u26a0\ufe0f",
                "informational": "\u2139\ufe0f",
                "newsletter": "\U0001f4f0",
                "spam": "\U0001f6ab",
            }
            emoji = category_emoji.get(email.get("ai_category", ""), "\U0001f4e7")
            priority = email.get("ai_priority", 3)
            priority_str = "\u2b50" * min(priority, 5) if priority else ""

            sender = email.get("from_name") or email.get("from_address", "Unknown")
            text = f"{emoji} *New Email*\n\n"
            text += f"*From:* {sender}\n"
            text += f"*Subject:* {email.get('subject', '(no subject)')}\n"
            if priority_str:
                text += f"*Priority:* {priority_str}\n"
            if email.get("ai_summary"):
                text += f"\n_{email['ai_summary']}_\n"

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Reply", callback_data=f"email_reply_{email['id']}"),
                        InlineKeyboardButton("Archive", callback_data=f"email_archive_{email['id']}"),
                        InlineKeyboardButton("Star", callback_data=f"email_star_{email['id']}"),
                    ],
                    [
                        InlineKeyboardButton("Mark Read", callback_data=f"email_read_{email['id']}"),
                    ],
                ]
            )

            loop = gateway._loop
            asyncio.run_coroutine_threadsafe(
                gateway._application.bot.send_message(
                    chat_id=telegram_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                ),
                loop,
            )
        except Exception as e:
            logger.error(f"Send email notification failed: {e}")

    def _send_email_telegram_digest(self, gateway, telegram_id, emails):
        """Send a digest of non-urgent emails via Telegram."""
        try:
            import asyncio

            text = f"\U0001f4ec *Email Digest* ({len(emails)} new)\n\n"
            for i, email in enumerate(emails[:10], 1):
                sender = email.get("from_name") or email.get("from_address", "Unknown")
                subject = email.get("subject", "(no subject)")
                cat = email.get("ai_category", "unknown")
                text += f"{i}. *{sender}*: {subject} [{cat}]\n"

            if len(emails) > 10:
                text += f"\n... and {len(emails) - 10} more"

            text += "\n\nUse /inbox to see all unread emails."

            loop = gateway._loop
            asyncio.run_coroutine_threadsafe(
                gateway._application.bot.send_message(chat_id=telegram_id, text=text, parse_mode="Markdown"),
                loop,
            )
        except Exception as e:
            logger.error(f"Send email digest failed: {e}")

    # ------------------------------------------------------------------
    # A.R.C.H.I.E. COO Approval Worker
    # ------------------------------------------------------------------

    def _archie_coo_approval_worker(self):
        """A.R.C.H.I.E. auto-approves low-risk Tier-2 items as COO.

        Reads 'archie_coo_approve' from autonomy_config (JSONB):
          {"types": [...], "contractor_cost_ceiling_usd": 2.0}
        Flips matching pending items to 'approved' so _process_approval_queue
        executes them on its next 60s tick. Sends Kytran a Telegram notice
        (informational — not a prompt) for transparency.
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT config_value FROM autonomy_config WHERE config_key = 'archie_coo_approve'")
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return

            cfg = row["config_value"] if isinstance(row["config_value"], dict) else {}
            coo_types = cfg.get("types", [])
            cost_ceiling = float(cfg.get("contractor_cost_ceiling_usd", 2.0))

            if not coo_types:
                cur.close()
                conn.close()
                return

            cur.execute(
                """
                SELECT id, action_type, action_data, reason, requested_by
                FROM autonomy_approval_queue
                WHERE status = 'pending' AND tier = 2 AND action_type = ANY(%s)
                ORDER BY created_at ASC
                LIMIT 5
                """,
                (coo_types,),
            )
            items = cur.fetchall()

            if not items:
                cur.close()
                conn.close()
                return

            approved_count = 0
            for item in items:
                try:
                    adata = (
                        item["action_data"]
                        if isinstance(item["action_data"], dict)
                        else json.loads(item["action_data"] or "{}")
                    )

                    # contractor_dispatch: enforce cost ceiling
                    if item["action_type"] == "contractor_dispatch":
                        est_cost = float(adata.get("estimated_cost_usd") or 0)
                        if est_cost > cost_ceiling:
                            logger.info(
                                "[coo_approval] Skipping contractor #%s — cost $%.2f > ceiling $%.2f",
                                item["id"],
                                est_cost,
                                cost_ceiling,
                            )
                            continue

                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'approved',
                            approved_at = NOW(),
                            execution_result = jsonb_build_object(
                                'approved_by_role', 'coo',
                                'approved_by_agent', 'A.R.C.H.I.E.',
                                'auto_approval', true
                            ),
                            updated_at = NOW()
                        WHERE id = %s AND status = 'pending'
                        """,
                        (item["id"],),
                    )
                    conn.commit()
                    approved_count += 1
                    logger.info(
                        "[coo_approval] A.R.C.H.I.E. approved #%s: %s",
                        item["id"],
                        item["action_type"],
                    )
                    log_governance_event(
                        "autonomy_approval",
                        f"coo_approve:{item['action_type']}",
                        "approved",
                        {"approval_id": item["id"], "approved_by": "A.R.C.H.I.E."},
                    )
                    # Inform Kytran — non-blocking, non-fatal
                    try:
                        from services.telegram_service import send_info  # noqa: PLC0415

                        reason_preview = (item["reason"] or "")[:160]
                        send_info(
                            f"COO auto-approved: {item['action_type']}\n"
                            f"Requested by: {item['requested_by']}\n"
                            f"Reason: {reason_preview}",
                            source_agent="A.R.C.H.I.E.",
                        )
                    except Exception:
                        pass

                except Exception as item_exc:
                    logger.error("[coo_approval] Error on #%s: %s", item["id"], item_exc)
                    conn.rollback()

            cur.close()
            conn.close()
            if approved_count:
                logger.info("[coo_approval] %d item(s) approved this cycle", approved_count)

        except Exception as exc:
            logger.error("[coo_approval] Worker error: %s", exc)

    # ------------------------------------------------------------------
    # Approval Queue Processor
    # ------------------------------------------------------------------

    def _signal_calendar_release(self):
        """S.I.G.N.A.L. calendar Phase 2 (#3990): promote due scheduled posts
        into the linkedin_post approval queue, 1/account/run."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.signal_calendar_service import release_due_posts

            result = release_due_posts()
            if result.get("total_released"):
                logger.info(f"[signal-calendar] daily release: {result}")
        except Exception as e:
            logger.error(f"[signal-calendar] daily release failed: {e}")

    def _browser_session_health_probe(self):
        """#3708 phase 2: READ-probe each active cookie session; stale ones flip."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.browser_profile_service import run_session_health_probe

            run_session_health_probe()
        except Exception as e:
            logger.error(f"[session-probe] job failed: {e}")

    def _browser_profile_keepwarm(self):
        """#3982: daily READ through each established browser profile."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.browser_profile_service import run_keepwarm

            run_keepwarm()
        except Exception as e:
            logger.error(f"[keepwarm] job failed: {e}")

    def _signal_comment_pipeline(self):
        """S.I.G.N.A.L. #3992: poll comment threads on our posts, then draft
        replies for new comments → Tier-2 Telegram approvals."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.linkedin_comment_monitor import (
                draft_comment_replies,
                run_comment_monitor,
            )

            polled = run_comment_monitor()
            drafted = draft_comment_replies()
            if polled.get("new_comments") or drafted.get("drafted"):
                logger.info(f"[signal-comments] polled={polled} drafted={drafted}")
        except Exception as e:
            logger.error(f"[signal-comments] pipeline failed: {e}")

    def _signal_calendar_topup(self):
        """S.I.G.N.A.L. calendar Phase 3 (#3991): generate fresh posts for
        accounts whose scheduled backlog has thinned."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.signal_calendar_service import top_up_calendars

            result = top_up_calendars()
            logger.info(f"[signal-calendar] top-up: {result}")
        except Exception as e:
            logger.error(f"[signal-calendar] top-up failed: {e}")

    def _signal_engagement_monitor(self):
        """S.I.G.N.A.L. engagement Phase 2: scan the feed and PROPOSE approval-gated
        likes/comments (Tier-2 Telegram). Flag-gated OFF by default — enable via
        work_control 'signal_engagement_monitor' when ready (avoids surprise
        approval spam). Human Approve/Deny is the relevance filter."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.work_control_service import is_enabled

            if not is_enabled("signal_engagement_monitor", default=False):
                return
            from services.signal_engagement_service import run_fleet_engagement_monitor

            # S7-P1-4a: the fleet driver runs the per-account monitor for every agent in
            # signal:engagement_monitor_agent_ids (default [342]), each with its own
            # registry voice + daily budget + the global anti-spam ledger.
            # Comments are an extra opt-in: each is S.I.G.N.A.L.-drafted then queued as its
            # OWN Tier-2 Telegram approval — never auto-posted (work_control
            # 'signal_engagement_comments', default OFF = likes only).
            result = run_fleet_engagement_monitor(
                include_comments=is_enabled("signal_engagement_comments", default=False)
            )
            if result.get("proposed"):
                logger.info(f"[signal-engagement] monitor: {result}")
            # Cross-account boosting (owner 2026-07-02): each identity likes the OTHER's
            # fresh posts + comments — own-content, no scraping, Tier-2 approvals.
            try:
                from services.signal_engagement_service import run_cross_boost

                boost = run_cross_boost()
                # Logging is proposal-gated: at most ONE info line per 8h tick, and
                # only when something was actually proposed — no hot-path overhead.
                if boost.get("proposed"):
                    logger.info(f"[signal-engagement] cross-boost: {boost}")
            except Exception as xb_err:
                logger.warning(f"[signal-engagement] cross-boost failed: {xb_err}")
        except Exception as e:
            logger.error(f"[signal-engagement] monitor failed: {e}")

    def _reset_engagement_budgets(self):
        """S7-P1-4b: daily (00:05 ET) — zero every agent's active_count_today and abandon
        stale 'pending' engagement-ledger orphans. Idempotent; always safe to run."""
        try:
            import sys as _sys

            _sys.path.insert(0, "/app")
            from services.signal_engagement_service import reset_daily_engagement_budgets

            res = reset_daily_engagement_budgets()
            logger.info(f"[signal-engagement] daily budget reset: {res}")
        except Exception as e:
            logger.error(f"[signal-engagement] budget reset failed: {e}")

    def _engine_autopull_cycle(self):
        """A.R.C.H.I.E. Building Machine autonomous scheduler (#380, ADR-008).

        Asks archie_engine over its WS bridge to pull ONE in-scope platform issue
        and build a GATED PR vs archie-platform. Live kill switch via work_control
        ("engine_autopull_cycle", default-on); fail-safe — any error is a no-op for
        the cycle. The engine enforces scope, dedup-rotation (#4322 + DedupTracker),
        and the never-merge / auto-merge-gate invariants on its side."""
        try:
            from services.work_control_service import is_enabled

            if not is_enabled("engine_autopull_cycle", default=True):
                return
        except Exception:
            return  # control plane unavailable → do nothing

        # #4343 P1c: engine builds are GPU-bound (qwen2.5-coder:7b plan) and long. Only
        # PROACTIVELY autopull when the GPU subcluster has interactive headroom — otherwise
        # defer this cycle (retry in 6h) so a build doesn't pile onto a saturated GPU cluster
        # (the observed >20-min engine queue behind WTF) or grind on the hub CPU while the
        # Starships rest. On-demand cockpit/TUI builds are NOT gated here. Fail-open.
        try:
            from services.cluster_slots import should_admit_batch

            admit, _rec, _slots = should_admit_batch(target_model="qwen2.5-coder:7b", gpu_bound=True)
            if not admit:
                logger.info(
                    "[engine-autopull] GPU subcluster has no headroom (gpu_free<=reserve) — " "deferring this cycle"
                )
                return
        except Exception:
            pass  # helper unavailable → proceed (fail-open, today's behavior)

        import asyncio

        async def _ask_engine():
            import json as _json

            import websockets

            uri = "ws://archie_engine:9090"
            async with websockets.connect(uri, open_timeout=15, close_timeout=5) as ws:
                await ws.send(_json.dumps({"type": "pull_repair_work"}))
                # 900s: a model_override coder dispatch is structurally ~242s on the hub
                # (validated — same warm or cold; it's the cold-load-queue path, not a
                # one-time load), so a build with plan retries + apply/test/push needs a
                # wide window (#380 Phase 3). max_instances=1+coalesce prevent overlap.
                raw = await asyncio.wait_for(ws.recv(), timeout=900)
                return _json.loads(raw) if raw else {}

        # Build SEVERAL issues per cycle, not one. Each call to the engine records its pick in
        # the engine-side DedupTracker, so successive calls naturally rotate to the next
        # un-attempted issue — no engine-side restructure needed, and pull_and_build keeps its
        # single-build contract (and its tests) intact.
        #
        # Tunable live, no deploy: platform_settings "engine:autopull:builds_per_cycle".
        # Default 3 — at ~47s per build (measured on PR #2348) that is ~2.5 min of an hourly
        # cycle. Raise it once the backlog justifies it; the GPU-headroom check above already
        # skips the whole cycle when the subcluster is busy.
        per_cycle = 3
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute(
                    "SELECT value FROM platform_settings WHERE key = %s",
                    ("engine:autopull:builds_per_cycle",),
                )
                _row = cur.fetchone()
            per_cycle = int(str((_row or {}).get("value") or "3").strip() or "3")
        except Exception:
            pass  # unset/unreadable -> default 3
        per_cycle = max(1, min(per_cycle, 10))  # hard bound: never let a bad setting run away

        for i in range(per_cycle):
            try:
                result = asyncio.run(_ask_engine())
            except Exception as e:
                logger.warning(f"[engine-autopull] build {i + 1}/{per_cycle} failed (no-op): {e}")
                break
            logger.info(f"[engine-autopull] build {i + 1}/{per_cycle} result: {result}")
            # Stop early when there is nothing left to do — a no-op means the queue held no
            # in-scope, un-attempted, non-stale issue, so further calls this cycle would only
            # repeat that answer.
            if result.get("skipped") or not result.get("issue_id"):
                logger.info("[engine-autopull] no further work this cycle — stopping after %d", i + 1)
                break

    # Wedge detection needs TWO signals, not one. Wait-age alone is a
    # false-positive generator: a single legitimately slow action holds the
    # max_instances=1 slot, leaves approved rows waiting, and trips the alarm
    # every time. Measured live 2026-08-15: website_deploy #10558 ran 16 min
    # (13:17:13 -> 13:33:13); the queue then drained 10 items in ~3 min at
    # ~20s each. The executor was healthy the whole time, but this watchdog
    # paged "likely wedged" and its remedy text told the operator to restart
    # archie_scheduler — MID-DEPLOY. A restart there destroys in-flight work.
    #
    # Progress = MAX(executed_at): the executor's own heartbeat. Same shape as
    # backup posture measuring last SUCCESS rather than last attempt (#5094).
    # Rows waiting + recent progress = BUSY. Rows waiting + no progress = WEDGED.
    _APPROVAL_WATCHDOG_STALE_MIN = 10
    _APPROVAL_WATCHDOG_PROGRESS_MIN = 30

    def _approval_queue_watchdog(self):
        """Observer-first wedge detector: alert when owner-approved actions sit
        unexecuted AND the executor has completed nothing recently.

        Two conditions must BOTH hold before this pages:
          1. approved rows waiting  > 'watchdog:approval_queue:stale_min'    (10 min)
          2. no item completed for  > 'watchdog:approval_queue:progress_min' (30 min)

        Condition 2 is what distinguishes a wedge from a slow item. Without it
        every long action (deploys, browser/LinkedIn batches) fires a false
        "wedged, restart the scheduler" alert whose remedy is destructive.

        progress_min MUST stay above the slowest single action; raise it if a
        legitimately slower action is introduced. Both thresholds are tunable
        live via platform_settings — no deploy needed.

        A queue that has NEVER executed anything cannot page a fresh install:
        with no approved rows, condition 1 is false and we return early."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cur.execute(
                    "SELECT key, value FROM platform_settings WHERE key IN (%s, %s)",
                    (
                        "watchdog:approval_queue:stale_min",
                        "watchdog:approval_queue:progress_min",
                    ),
                )
                cfg = {r["key"]: r["value"] for r in (cur.fetchall() or [])}

                def _tunable(key: str, default: int) -> int:
                    try:
                        return int((cfg.get(key) or "") or default)
                    except Exception:
                        return default

                stale_min = _tunable("watchdog:approval_queue:stale_min", self._APPROVAL_WATCHDOG_STALE_MIN)
                progress_min = _tunable(
                    "watchdog:approval_queue:progress_min",
                    self._APPROVAL_WATCHDOG_PROGRESS_MIN,
                )

                cur.execute(
                    """
                    SELECT id, action_type, approved_at
                    FROM autonomy_approval_queue
                    WHERE status = 'approved'
                      AND approved_at < NOW() - make_interval(mins => %s)
                    ORDER BY approved_at ASC
                    LIMIT 5
                    """,
                    (stale_min,),
                )
                stalled = cur.fetchall()

                # Executor heartbeat: newest completion of ANY item. NULL only
                # when nothing has ever executed.
                cur.execute(
                    """
                    SELECT EXTRACT(epoch FROM (NOW() - MAX(executed_at))) / 60.0
                               AS progress_age_min
                    FROM autonomy_approval_queue
                    WHERE executed_at IS NOT NULL
                    """
                )
                prow = cur.fetchone() or {}
                raw_age = prow.get("progress_age_min")
                progress_age_min = None if raw_age is None else float(raw_age)
            finally:
                cur.close()
                conn.close()

            if not stalled:
                return

            ids = ", ".join(f"#{r['id']} {r['action_type']}" for r in stalled)

            # BUSY, not wedged. Log it — a silent healthy path is
            # indistinguishable from a dead one (#5606) — but do NOT page.
            if progress_age_min is not None and progress_age_min < progress_min:
                logger.info(
                    f"[approval_watchdog] {len(stalled)} approved action(s) waiting "
                    f">{stale_min}min ({ids}), but an item completed "
                    f"{progress_age_min:.1f}min ago (<{progress_min}min threshold) — "
                    "executor BUSY on a slow item, not wedged; no alert"
                )
                return

            age_txt = (
                "no item has EVER completed"
                if progress_age_min is None
                else f"no item has completed in {progress_age_min:.0f} min"
            )
            logger.warning(
                f"[approval_watchdog] {len(stalled)}+ approved action(s) unexecuted "
                f">{stale_min}min: {ids} — {age_txt} (>{progress_min}min): executor stalled"
            )
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.telegram_service import send_system

                send_system(
                    "Approval executor stalled",
                    f"{len(stalled)}+ approved action(s) unexecuted for >{stale_min} min: {ids}. "
                    f"Confirmed stalled, not merely slow: {age_txt} "
                    f"(threshold {progress_min} min). "
                    "DIAGNOSE BEFORE RESTARTING — check which action is in flight via "
                    "`docker logs archie_scheduler | grep approval_queue` and the newest "
                    "executed_at in autonomy_approval_queue. Restarting archie_scheduler "
                    "kills an in-flight deploy or backup mid-run.",
                    source="approval_queue_watchdog",
                )
            except Exception as te:
                logger.error(f"[approval_watchdog] telegram alert failed: {te}")
        except Exception as e:
            logger.error(f"[approval_watchdog] check failed: {e}")

    # #4632: extra attempts granted to approval executions killed by INFRASTRUCTURE
    # (browser sidecar / container restart mid-task) rather than a real skill verdict.
    _APPROVAL_INFRA_RETRY_CAP = 2

    @staticmethod
    def _is_infra_failure(result: dict) -> bool:
        """True when an executed:False result is an INFRASTRUCTURE death — the browser
        sidecar/container restarted mid-task (run_skill_sync poll deadline 'Timeout
        after Ns', vanished task id, connection refused) — rather than a real skill
        verdict (e.g. 'comment could not be confirmed on the page'). Infra deaths get
        REQUEUED (#4632, live case: approval #1823 killed by an archie_browser rebuild);
        real verdicts stay terminal."""
        if not isinstance(result, dict):
            return False
        inner = result.get("result") if isinstance(result.get("result"), dict) else {}
        if str(inner.get("_status") or "") == "timeout":
            return True
        err = " ".join(str(x) for x in (result.get("error"), inner.get("error")) if x).lower()
        if "timeout after" in err or "connection refused" in err or "connection error" in err:
            return True
        # #5403: GitHub-MECHANICAL merge failures. The human's DECISION stays
        # valid — what failed is the mechanism (draft-405, transient GitHub
        # 5xx, rate limit). Terminal-failing these BURNS a Tier-3 approval:
        # 2026-07-29, approval 6485 / PR #2549 — Kytran approved, the 405
        # ("Pull Request is still a draft") flipped the row 'failed', nothing
        # re-raised. Requeue instead (bounded by _APPROVAL_INFRA_RETRY_CAP;
        # exhaustion still alerts via skill_failure_alerts). Real AUTHORIZATION
        # refusals (governance_blocked, denied, no approver) match none of
        # these and stay terminal.
        return (
            "still a draft" in err
            or "bad gateway" in err
            or "service unavailable" in err
            or "rate limit" in err
            or " 502" in err
            or " 503" in err
        )

    def _process_approval_queue(self):
        """Process the approval queue: execute approved, expire stale."""
        start = time.time()
        processed = 0
        failed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if not self._is_enabled(cur, "approval_queue_enabled"):
                cur.close()
                conn.close()
                return

            # 1. Expire stale pending tier-2 items
            cur.execute(
                """
                UPDATE autonomy_approval_queue
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'pending' AND expires_at < NOW()
                RETURNING id, action_type
                """
            )
            expired = cur.fetchall()
            for item in expired:
                logger.info(f"Expired approval #{item['id']}: {item['action_type']}")
                log_governance_event(
                    "autonomy_approval",
                    f"expire:{item['action_type']}",
                    "expired",
                    {"approval_id": item["id"]},
                )
            conn.commit()

            # 1b. Handle rejected media_generation items — update media queue
            cur.execute(
                """
                SELECT id, action_type, action_data
                FROM autonomy_approval_queue
                WHERE status = 'rejected' AND action_type = 'media_generation'
                  AND updated_at > NOW() - INTERVAL '5 minutes'
                """
            )
            rejected_media = cur.fetchall()
            for item in rejected_media:
                try:
                    rdata = (
                        item["action_data"]
                        if isinstance(item["action_data"], dict)
                        else json.loads(item["action_data"])
                    )
                    queue_id = rdata.get("queue_id")
                    if queue_id:
                        cur.execute(
                            """
                            UPDATE media_generation_queue
                            SET status = 'rejected', completed_at = NOW()
                            WHERE id = %s AND status = 'awaiting_approval'
                            """,
                            (queue_id,),
                        )
                    # Mark as handled so we don't re-process
                    cur.execute(
                        "UPDATE autonomy_approval_queue SET status = 'expired', updated_at = NOW() WHERE id = %s",
                        (item["id"],),
                    )
                    logger.info(f"Rejected media generation #{queue_id} (approval #{item['id']})")
                except Exception as rej_err:
                    logger.error(f"Failed to handle rejected media #{item['id']}: {rej_err}")
            if rejected_media:
                conn.commit()

            # 2. Execute approved items
            cur.execute(
                """
                SELECT id, action_type, action_data, tier, requested_by, reason
                FROM autonomy_approval_queue
                WHERE status = 'approved'
                ORDER BY priority ASC, created_at ASC
                LIMIT 10
                """
            )
            approved = cur.fetchall()

            for item in approved:
                # Stuck-job guard: a string of slow browser/LLM items (120-180s
                # each, up to 10/batch) can wedge this max_instances=1 job for
                # ~30 min — every 60s tick then logs "max instances reached"
                # and the queue looks stuck (2026-06-10 FR post incident). Cap
                # the batch; remaining items run on the next tick.
                if time.time() - start > 240:
                    logger.warning(
                        "[approval_queue] batch deadline (240s) hit after "
                        f"{processed} item(s) — deferring rest to next tick"
                    )
                    break
                try:
                    result = self._execute_approved_action(cur, conn, item)
                    # #4327: respect the branch's own success signal. Previously this
                    # marked EVERY non-exception return as 'executed' — so a timed-out
                    # or failed linkedin_post (which returns executed:False) showed as
                    # done without ever publishing. Default True keeps back-compat for
                    # branches that don't return an 'executed' key (send_email, etc.).
                    _ok = (result or {}).get("executed", True)
                    # #4632: an infra-killed execution (sidecar/container restart
                    # mid-task) is REQUEUED for a later tick — status stays
                    # 'approved' so the next 60s cycle retries — instead of being
                    # terminally failed: the action never reached a real verdict.
                    # Bounded by _APPROVAL_INFRA_RETRY_CAP; comment double-posts on
                    # retry are guarded by the skill's pre-submit already-present
                    # check (linkedin_comment).
                    if not _ok and self._is_infra_failure(result or {}):
                        _data = (
                            item["action_data"]
                            if isinstance(item["action_data"], dict)
                            else json.loads(item["action_data"] or "{}")
                        )
                        _retries = int(_data.get("_infra_retries") or 0)
                        if _retries < self._APPROVAL_INFRA_RETRY_CAP:
                            _data["_infra_retries"] = _retries + 1
                            cur.execute(
                                "UPDATE autonomy_approval_queue SET action_data = %s, updated_at = NOW() WHERE id = %s",
                                (json.dumps(_data), item["id"]),
                            )
                            conn.commit()
                            logger.warning(
                                f"[approval_queue] #{item['id']} {item['action_type']} infra-failure — "
                                f"requeued (retry {_retries + 1}/{self._APPROVAL_INFRA_RETRY_CAP}): "
                                f"{(result or {}).get('error') or 'timeout'}"
                            )
                            continue
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = %s, executed_at = NOW(),
                            execution_result = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        ("executed" if _ok else "failed", json.dumps(result or {}), item["id"]),
                    )
                    conn.commit()
                    if _ok:
                        processed += 1
                    else:
                        failed += 1
                        # #5627: a failed linkedin_* action whose OWN diagnostics show
                        # LinkedIn's login/authwall is POSITIVE knowledge the posting
                        # profile is logged out. Feed it back immediately instead of
                        # waiting for the 4-hourly probe — on 2026-08-15 that window
                        # let 3 producers burn 5 posts over 50 minutes while the
                        # evidence sat unread in execution_result.
                        self._maybe_flag_linkedin_authwall(item, result or {})

                    # Layer A Phase 1 — alert on logical failure (success path that returned an error)
                    try:
                        from services.skill_failure_alerts import alert_on_skill_failure

                        alert_on_skill_failure(
                            approval_id=item["id"],
                            skill_name=item.get("action_type", "unknown"),
                            execution_result=result or {},
                        )
                    except Exception:
                        logger.exception("[skill_failure_alerts] hook failed")

                    log_governance_event(
                        "autonomy_execution",
                        f"execute:{item['action_type']}",
                        "success" if _ok else "failed",
                        {"approval_id": item["id"], "result": result},
                    )

                except Exception as e:
                    logger.error(f"Failed to execute approved action #{item['id']}: {e}")
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'failed', execution_result = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (json.dumps({"error": str(e)}), item["id"]),
                    )
                    conn.commit()
                    failed += 1

                    # Layer A Phase 1 — alert on hard exception
                    try:
                        from services.skill_failure_alerts import alert_on_skill_failure

                        alert_on_skill_failure(
                            approval_id=item["id"],
                            skill_name=item.get("action_type", "unknown"),
                            execution_result={"success": False, "error": str(e), "_status": "exception"},
                        )
                    except Exception:
                        logger.exception("[skill_failure_alerts] hook failed")

            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Approval queue processing error: {e}")
            failed += 1

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or failed > 0 or (expired if "expired" in dir() else []):
            self._log_cycle("approvals", processed, failed, duration_ms)

    @staticmethod
    def _maybe_flag_linkedin_authwall(item: dict, result: dict) -> None:
        """#5627: close the auth feedback loop for LinkedIn posting failures.

        The #1831 release guard gates on browser_sessions.status='stale', which
        ONLY the 4-hourly health probe used to set — so a logout landed a
        multi-hour window where releases/top-ups kept burning approvals while
        every failure's diagnostics plainly showed the login page. When a
        failed linkedin_* result carries an authwall signature, mark the
        posting profile stale NOW (the guard holds everything from the next
        cycle) and fire the deduped re-auth alert the owner never got on
        2026-08-15. Best-effort: never raises into the executor.
        """
        try:
            action_type = str(item.get("action_type") or "")
            if not action_type.startswith("linkedin"):
                return
            blob = json.dumps(result, default=str).lower()
            if not any(sig in blob for sig in ("uas/login", "authwall", "session_redirect", "checkpoint/challenge")):
                return
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            data = item.get("action_data")
            if not isinstance(data, dict):
                try:
                    data = json.loads(data or "{}")
                except (TypeError, ValueError):
                    data = {}
            account = (data.get("account") or data.get("post_type") or "").strip() or None
            agent_id = 342
            try:
                from services import signal_accounts

                if account:
                    agent_id = signal_accounts.browser_id_for(account) or 342
            except Exception:
                pass  # default 342 — the shared majors profile
            from services import browser_session_service

            browser_session_service.mark_stale(
                agent_id,
                "linkedin",
                f"authwall in failed {action_type} approval #{item.get('id')} (#5627 feedback)",
            )
            try:
                from services.signal_calendar_service import _alert_linkedin_stale

                _alert_linkedin_stale(account or "personal", agent_id)
            except Exception:
                logger.warning("authwall re-auth alert failed (profile IS marked stale)", exc_info=True)
            logger.warning(
                "[approval_queue] %s #%s hit LinkedIn AUTHWALL — profile agent %s marked stale (#5627)",
                action_type,
                item.get("id"),
                agent_id,
            )
        except Exception:
            logger.exception("_maybe_flag_linkedin_authwall failed (non-fatal)")

    def _execute_approved_action(self, cur, conn, item: dict) -> dict:
        """Execute an approved action from the approval queue."""
        action_type = item["action_type"]
        data = item["action_data"] if isinstance(item["action_data"], dict) else json.loads(item["action_data"])

        if action_type == "send_email":
            # Queue the email
            cur.execute(
                """
                INSERT INTO email_queue (recipient, subject, body_html, scheduled_for, priority, metadata)
                VALUES (%s, %s, %s, NOW(), 2, %s)
                """,
                (
                    data.get("recipient", ""),
                    data.get("subject", ""),
                    data.get("body_html", ""),
                    json.dumps({"source": "approval_queue", "approval_id": item["id"]}),
                ),
            )
            conn.commit()
            return {"queued": True, "recipient": data.get("recipient")}

        elif action_type == "notification":
            self._create_notification(
                cur,
                notification_type=data.get("type", "info"),
                title=data.get("title", "Notification"),
                message=data.get("message", ""),
                source="approval_queue",
            )
            conn.commit()
            return {"notified": True}

        elif action_type == "agent_password_reset":
            # #5303 (owner direction 2026-07-27): agent logins are managed by Account
            # Center; a rotation is an ADMIN action that executes ONLY here — after the
            # Tier-2 Telegram approval that routed this item to us. The service is
            # HARD-scoped to the claude/archie agent accounts and its result carries
            # NO secret (the new password lands only in the gitignored .env stores).
            from services.agent_credential_service import reset_agent_password

            return reset_agent_password(data.get("username", ""))

        elif action_type == "pr_merge":
            # Tier-3 / sensitive-path PR merge, approved on EITHER surface (#5283, #5338).
            #
            # IDEMPOTENT BY CONSTRUCTION. The Telegram button merges inside
            # _pr_merge_callback and THEN flips this row to 'approved', so this
            # executor routinely meets a PR that is already merged. Treating that
            # as a failure is exactly what happened to approval #5816: PR #2522
            # merged at 00:29:40Z and the row read 'failed' 18s later with
            # "Unknown action type: pr_merge" — a successful merge recorded as a
            # failure, because this branch did not exist at all. Already-merged
            # is SUCCESS, and the Approvals-tab tap now merges for real instead
            # of silently doing nothing.
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from tools.repair_bay.services.github_service import get_pr_status, merge_pr
                from tools.repair_bay.services.pr_review_service import (
                    get_review,
                    resolve_pr_merge_approval,
                )

                pr_num = int(data.get("pr_number") or 0)
                if not pr_num:
                    return {"executed": False, "error": "pr_merge approval carries no pr_number"}
                repo = data.get("repo")

                status = get_pr_status(pr_num) or {}
                if status.get("merged"):
                    resolve_pr_merge_approval(pr_num, approved=True)
                    logger.info("pr_merge: PR #%s was already merged — resolving row as done", pr_num)
                    return {"executed": True, "pr_number": pr_num, "note": "already merged on the other surface"}

                # A pr_merge row IS a human decision — merging on one that no
                # human is attributed to would hand an automated actor the very
                # authority this queue exists to withhold. pr_merge is
                # deliberately absent from archie_coo_approve.types; this is the
                # belt to that suspenders. Safety is universal, authority is
                # per-actor (#2459/#2460).
                approver = None
                try:
                    cur.execute(
                        "SELECT approved_by FROM autonomy_approval_queue WHERE id = %s",
                        (item["id"],),
                    )
                    _ar = cur.fetchone()
                    if _ar:
                        approver = _ar["approved_by"] if isinstance(_ar, dict) else _ar[0]
                except Exception as _ae:
                    logger.warning("pr_merge: could not read approver for #%s: %s", item["id"], _ae)
                if not approver:
                    return {
                        "executed": False,
                        "error": "pr_merge has no human approver — refusing (a Tier-3 PR is never auto-merged)",
                    }

                # #5834: human_override=True bypasses _automerge_governance_ok()
                # ENTIRELY — verdict, FRESHNESS and tier ceiling. The tap above proves
                # AUTHORITY (a human cleared the allowlist, which is exactly what the
                # override is for), but it cannot prove the approval still describes the
                # code. An approval raised at time T is tapped at T+n; every commit that
                # landed in between merges UNREVIEWED, silently.
                #
                # Decision #953: safety properties are UNIVERSAL, authority limits are
                # PER-ACTOR. Freshness is a SAFETY property — it binds the owner too,
                # because nobody can review a commit that did not exist when they were
                # asked. The allowlist is an AUTHORITY limit, and a human may clear it.
                # So: restore the safety check, keep the override for authority.
                #
                # Nearly happened 2026-08-19: approval #11693 (PR #2710) was raised at
                # 22:57; the fix removing a query that took this very endpoint from ~70ms
                # to 57-84s landed AFTER it. A tap in that window would have merged the
                # slow version. It resolved only because the PR was re-reviewed.
                _fresh_err = None
                try:
                    from tools.repair_bay.services.github_service import (  # noqa: PLC0415
                        _automerge_governance_ok,
                    )
                    from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
                        verdict_is_approved,
                    )

                    _row = get_review(pr_num, repo=repo) or {}
                    _summary = _row.get("ai_summary") or ""
                    _vok = bool(_summary) and verdict_is_approved(_summary)
                    _ok, _why = _automerge_governance_ok(pr_num, authority="coo") if _vok else (False, "")
                    _fresh_err = tab_merge_refusal(_summary, _vok, _ok, _why)
                except Exception as _fe:  # noqa: BLE001
                    # FAIL CLOSED. An unreadable verdict is not a fresh one, and this
                    # path ends in an unrevertable merge to main.
                    _fresh_err = f"could not verify the verdict ({_fe}) — refusing rather than guessing"

                if _fresh_err:
                    logger.warning("[pr_merge] REFUSING PR #%s from the Approvals tab: %s", pr_num, _fresh_err)
                    return {
                        "executed": False,
                        "pr_number": pr_num,
                        "error": (
                            f"Refusing to merge PR #{pr_num}: {_fresh_err}. "
                            "Re-run the review, then approve again — the row is left pending."
                        ),
                    }

                result = merge_pr(pr_num, "squash", repo=repo, human_override=True)
                merged = bool(result.get("merged"))
                if merged:
                    resolve_pr_merge_approval(pr_num, approved=True, user_id=approver)
                    logger.info("pr_merge: PR #%s merged via the Approvals tab (approver=%s)", pr_num, approver)
                return {
                    "executed": merged,
                    "pr_number": pr_num,
                    "error": None if merged else (result.get("error") or "merge refused"),
                }
            except Exception as pm_err:
                logger.error("pr_merge execution failed: %s", pm_err)
                return {"executed": False, "error": str(pm_err)}

        elif action_type == "external_webhook":
            import requests

            resp = requests.post(
                data.get("url", ""),
                json=data.get("payload", {}),
                headers=data.get("headers", {}),
                timeout=30,
            )
            return {"status_code": resp.status_code, "response": resp.text[:500]}

        elif action_type == "media_generation":
            # Approved paid media generation — update queue and generate
            queue_id = data.get("queue_id")
            if not queue_id:
                return {"error": "No queue_id in action_data"}

            try:
                from external_providers import generate_media

                # Update queue status to generating
                cur.execute(
                    """
                    UPDATE media_generation_queue
                    SET status = 'generating', started_at = NOW()
                    WHERE id = %s AND status = 'awaiting_approval'
                    RETURNING id, request_type, prompt, params, provider_key
                    """,
                    (queue_id,),
                )
                queue_row = cur.fetchone()
                conn.commit()

                if not queue_row:
                    return {"error": f"Queue entry {queue_id} not found or not awaiting approval"}

                # Build the generation request
                gen_params = (
                    queue_row["params"]
                    if isinstance(queue_row["params"], dict)
                    else json.loads(queue_row["params"] or "{}")
                )
                gen_request = {
                    "type": queue_row["request_type"],
                    "prompt": queue_row["prompt"],
                    "params": gen_params,
                }

                result = generate_media(queue_row["provider_key"], gen_request)

                if result.get("success"):
                    # Save asset to media_assets
                    cur.execute(
                        """
                        INSERT INTO media_assets
                        (asset_type, title, prompt, file_path, file_size_bytes,
                         mime_type, provider_key, model_used, cost_usd,
                         generation_params, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            queue_row["request_type"],
                            gen_request["prompt"][:100],
                            gen_request["prompt"],
                            result.get("file_path", ""),
                            result.get("file_size", 0),
                            result.get("mime_type", ""),
                            queue_row["provider_key"],
                            result.get("model", ""),
                            result.get("cost", 0),
                            json.dumps(gen_params),
                            data.get("requested_by_user_id"),
                        ),
                    )
                    asset_id = cur.fetchone()["id"]

                    cur.execute(
                        """
                        UPDATE media_generation_queue
                        SET status = 'completed', result_asset_id = %s,
                            model_used = %s, completed_at = NOW()
                        WHERE id = %s
                        """,
                        (asset_id, result.get("model", ""), queue_id),
                    )
                    conn.commit()
                    return {"executed": True, "asset_id": asset_id, "file_path": result.get("file_path")}
                else:
                    cur.execute(
                        """
                        UPDATE media_generation_queue
                        SET status = 'failed', error_message = %s, completed_at = NOW()
                        WHERE id = %s
                        """,
                        (result.get("error", "Unknown error")[:500], queue_id),
                    )
                    conn.commit()
                    return {"executed": False, "error": result.get("error")}

            except Exception as media_err:
                logger.error(f"Media generation execution failed: {media_err}")
                cur.execute(
                    """
                    UPDATE media_generation_queue
                    SET status = 'failed', error_message = %s, completed_at = NOW()
                    WHERE id = %s
                    """,
                    (str(media_err)[:500], queue_id),
                )
                conn.commit()
                return {"executed": False, "error": str(media_err)}

        elif action_type == "cloud_throughput_escalation":
            # Approved paid cloud escalation — dispatch via bridge
            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                escalated_model = data.get("escalated_model", "")
                result = dispatcher._execute_llm(
                    model=escalated_model,
                    prompt=data.get("prompt_preview", ""),
                    system_prompt=None,
                    timeout=300,
                )
                dispatcher._log_escalation(
                    original_agent_id=None,
                    original_model=data.get("original_agent", "unknown"),
                    escalated_model=escalated_model,
                    escalated_provider=data.get("escalated_provider", "unknown"),
                    capability=data.get("capability", "unknown"),
                    module_id=data.get("module_id", "unknown"),
                    reason=f"Throughput: paid cloud approved (#{item['id']})",
                    failure_count=0,
                    approval_method="telegram",
                    success=result.get("success", False),
                )
                return {
                    "executed": True,
                    "model": escalated_model,
                    "success": result.get("success", False),
                }
            except Exception as esc_err:
                logger.error(f"Cloud throughput escalation failed: {esc_err}")
                return {"executed": False, "error": str(esc_err)}

        elif action_type == "create_agent":
            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                agent_id = dispatcher._create_agent_from_approval(data)
                if agent_id:
                    logger.info(f"Agent created from approval #{item['id']}: agent_id={agent_id}")
                    return {"executed": True, "agent_id": agent_id}
                else:
                    return {"executed": False, "error": "Creation returned None"}
            except Exception as create_err:
                logger.error(f"Agent creation from approval failed: {create_err}")
                return {"executed": False, "error": str(create_err)}

        elif action_type == "reactivate_agent":
            # Project #272 Phase 1 / Task #2107. Approved reactivation flips
            # a decommissioned agent to barracked. Consumer pairs with the
            # propose_reactivation() service helper; the actual state change
            # lives in agent_service.reactivate_agent() (single-writer).
            agent_id = data.get("agent_id")
            if not agent_id:
                return {"executed": False, "error": "No agent_id in action_data"}
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.agent_service import reactivate_agent

                result = reactivate_agent(
                    agent_id,
                    reason=data.get("reason", "approved reactivation"),
                )
                if result.get("success"):
                    logger.info(f"Agent {agent_id} reactivated from approval " f"#{item['id']}: {result.get('name')}")
                    return {"executed": True, **result}
                return {
                    "executed": False,
                    "error": result.get("error", "reactivate_agent failed"),
                }
            except Exception as react_err:
                logger.error(f"Agent reactivation from approval failed: {react_err}")
                return {"executed": False, "error": str(react_err)}

        elif action_type == "model_rightsizing":
            # P2-C part 2 (#381). Approved correctness-graded right-sizing — repoint an agent to a
            # smaller/faster model that holds quality (proposed by propose_model_rightsizing, ranked
            # by P2-A correctness). update_agent is the single-writer; agents.model is read live by
            # the dispatcher, and the right-sizer only ever proposes base model tags, so a bare model
            # column write is sufficient (no Modelfile regeneration needed). NEVER auto-applies.
            rs_agent_id = data.get("agent_id")
            new_model = data.get("new_model")
            if not rs_agent_id or not new_model:
                return {"executed": False, "error": "agent_id and new_model required in action_data"}
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.agent_service import update_agent

                ok = bool(update_agent(rs_agent_id, model=new_model))  # returns a bare bool
                if ok:
                    logger.info(
                        f"Agent {rs_agent_id} right-sized to {new_model} "
                        f"(was {data.get('old_model')}) from approval #{item['id']}"
                    )
                return {
                    "executed": ok,
                    "agent_id": rs_agent_id,
                    "new_model": new_model,
                    "old_model": data.get("old_model"),
                    "error": None if ok else "update_agent returned False (agent not found)",
                }
            except Exception as rs_err:
                logger.error(f"Model right-sizing from approval failed: {rs_err}")
                return {"executed": False, "error": str(rs_err)}

        elif action_type == "restart_container":
            # Project #272 Phase 2 / Task #2127. Approved recovery of a
            # DOWN critical container. The V.I.G.I.L. heartbeat job files
            # these; actual compose-up happens here only after approval.
            compose_service = data.get("compose_service") or data.get("container")
            if not compose_service:
                return {"executed": False, "error": "No compose_service in action_data"}
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.infra_heartbeat_service import restart_container

                result = restart_container(
                    compose_service,
                    reason=data.get("reason", "approved restart"),
                )
                if result.get("success"):
                    logger.info(f"Container {compose_service} restarted from approval " f"#{item['id']}")
                    return {"executed": True, **result}
                return {
                    "executed": False,
                    "error": result.get("error", "restart_container failed"),
                }
            except Exception as restart_err:
                logger.error(f"Container restart from approval failed: {restart_err}")
                return {"executed": False, "error": str(restart_err)}

        elif action_type in ("improvement_approve", "improvement_approve_red"):
            # Approved improvement proposal — trigger auto-execution pipeline.
            # improvement_approve_red = a RED Code-Health finding the owner just
            # approved from the Telegram card; identical execution from here.
            proposal_id = data.get("proposal_id")
            if not proposal_id:
                return {"executed": False, "error": "No proposal_id in action_data"}

            try:
                # Update proposal status to approved
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET status = 'approved',
                        approved_at = NOW(),
                        reviewed_at = NOW()
                    WHERE id = %s AND status IN ('pending', 'proposed', 'pending_approval')
                    RETURNING id
                    """,
                    (proposal_id,),
                )
                result = cur.fetchone()
                conn.commit()

                if not result:
                    return {
                        "executed": False,
                        "error": f"Proposal #{proposal_id} not found or already processed",
                    }

                # Check if this is a code_health_audit proposal — handled by repair pipeline, not old auto_run
                cur.execute(
                    "SELECT metadata->>'source' as source FROM improvement_proposals WHERE id = %s",
                    (proposal_id,),
                )
                src_row = cur.fetchone()
                proposal_source = (src_row.get("source") or "") if src_row else ""

                if proposal_source == "code_health_audit":
                    # Repair pipeline handles these via dispatch_proposal_fix
                    logger.info(
                        f"Proposal #{proposal_id} is code_health_audit — skipping old auto_run, "
                        f"repair pipeline will dispatch via Bridge"
                    )
                else:
                    # Trigger Phase 4 auto-execution for non-audit proposals
                    import threading

                    def _run_auto_execute():
                        try:
                            import sys

                            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                            from services.proposal_service import auto_run

                            auto_run(proposal_id)
                        except Exception as exec_err:
                            logger.error(f"Auto-execution failed for proposal #{proposal_id}: {exec_err}")

                    thread = threading.Thread(target=_run_auto_execute, daemon=True)
                    thread.start()

                logger.info(
                    f"Improvement proposal #{proposal_id} approved via autonomy queue, " f"auto-execution started"
                )
                return {"executed": True, "proposal_id": proposal_id}

            except Exception as imp_err:
                logger.error(f"Improvement approval execution failed: {imp_err}")
                return {"executed": False, "error": str(imp_err)}

        elif action_type == "backup_before_deploy":
            # Owner tapped Approve on "self-heal is paused, a backup is needed" (#4989).
            # W.A.R.D.E.N. refuses a medium-risk deploy when the primary backup is older than
            # its limit. Rather than dead-ending the held fixes, run the backup the gate is
            # asking for; they clear on the next drain cycle with the guard still fully intact.
            # NOTE this deliberately does NOT override the gate — it satisfies it.
            try:
                # Import without mutating global import order when we don't have to.
                # The previous form did an unconditional sys.path.insert(0, ...), which puts
                # this tree AHEAD of stdlib and first-party packages on every invocation —
                # with a package as generically named as `tools`, that is a real shadowing
                # risk, and it grew sys.path a little each time. (F.O.R.G.E. flagged it on
                # PR #2362.) Try the normal import first; only fall back to extending the
                # path, and APPEND so nothing can be shadowed.
                try:
                    from tools.backup_manager.backup_manager_routes import create_backup_programmatic
                except ImportError:
                    import sys

                    _pv2 = "/mnt/archie_brain/platform_v2"
                    if _pv2 not in sys.path:
                        sys.path.append(_pv2)
                    from tools.backup_manager.backup_manager_routes import create_backup_programmatic

                res = (
                    create_backup_programmatic(
                        description="Pre-deploy backup (self-heal gate)",
                        created_by_username="warden_gate",
                    )
                    or {}
                )
                if not res.get("success"):
                    return {
                        "executed": False,
                        "error": f"Backup failed: {str(res.get('error') or res)[:200]}",
                    }
                logger.info("backup_before_deploy: backup created, self-heal fixes unblocked")
                return {
                    "executed": True,
                    "result": "Backup complete — held fixes will be offered on the next drain cycle.",
                    "backup": {k: res.get(k) for k in ("backup_id", "file_path", "size_bytes") if k in res},
                }
            except Exception as _bk_err:
                logger.error("backup_before_deploy failed: %s", _bk_err)
                return {"executed": False, "error": f"Backup failed: {_bk_err}"}

        elif action_type == "deploy_approve":
            # Telegram-approved tiered deployment — run sandbox gate then deploy
            proposal_id = data.get("proposal_id")
            if not proposal_id:
                return {"executed": False, "error": "No proposal_id in action_data"}
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.proposal_service import _sandbox_gate, deploy_to_production
                from database import get_db_cursor

                with get_db_cursor() as (_conn, _cur):
                    _cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
                    proposal = _cur.fetchone()

                if not proposal:
                    return {"executed": False, "error": f"Proposal #{proposal_id} not found"}

                # Sandbox gate first
                gate = _sandbox_gate(proposal_id, proposal)
                if not gate["passed"]:
                    logger.warning(
                        "deploy_approve: sandbox gate FAILED for proposal #%s — %s/%s passed",
                        proposal_id,
                        gate["passed_count"],
                        gate["total"],
                    )
                    return {
                        "executed": False,
                        "error": f"Sandbox gate failed ({gate['passed_count']}/{gate['total']} P.R.O.B.E. tests). Production deploy blocked.",
                        "sandbox": gate,
                    }

                # Gate passed — deploy to production
                result = deploy_to_production(proposal_id)
                logger.info(
                    "deploy_approve: proposal #%s deployed after sandbox gate %s/%s passed",
                    proposal_id,
                    gate["passed_count"],
                    gate["total"],
                )
                return {
                    "executed": result["success"],
                    "proposal_id": proposal_id,
                    "sandbox": gate,
                    "error": result.get("error") if not result["success"] else None,
                }
            except Exception as da_err:
                logger.error("deploy_approve execution failed: %s", da_err)
                return {"executed": False, "error": str(da_err)}

        elif action_type == "website_deploy":
            # Telegram-approved website / VPS deploy (#4344 follow-up). Re-invoke the
            # deploy pipeline with approved=True so it SKIPS the risk gate and actually
            # deploys this time (no loop). action_data carries the full deploy context.
            try:
                import sys

                sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from services.deploy_service import run_deploy_pipeline

                cap = data.get("capability") or "deploy_static"
                res = run_deploy_pipeline(cap, {**data, "approved": True})
                ok = bool(getattr(res, "success", False))
                logger.info(
                    "website_deploy: %s %s after approval (%s)",
                    cap,
                    data.get("domain"),
                    "success" if ok else getattr(res, "error", "failed"),
                )
                return {
                    "executed": ok,
                    "domain": data.get("domain"),
                    "error": getattr(res, "error", None) if not ok else None,
                }
            except Exception as wd_err:
                logger.error("website_deploy execution failed: %s", wd_err)
                return {"executed": False, "error": str(wd_err)}

        elif action_type == "codex_promote":
            # Telegram-approved promotion of a previewed Codex PR: merge to main,
            # then flag deploy_pending so the HOST poller (codex-prod-deploy.sh)
            # does git-pull + safe_restart + verify on the host (the deploy step
            # can't run in-container). Merge only fires on this Tier-2 human approval.
            pr_number = data.get("pr_number")
            if not pr_number:
                return {"executed": False, "error": "No pr_number in action_data"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                from tools.repair_bay.services.github_service import merge_pr

                import re as _re

                # SECURITY: strict module allow-list (defence-in-depth vs injection
                # in the downstream host poller, which builds URLs/log strings).
                module = data.get("module")
                if module is not None and not _re.fullmatch(r"[a-z0-9_-]{1,40}", str(module)):
                    return {
                        "executed": False,
                        "error": f"invalid module: {module!r}",
                        "deploy_pending": False,
                    }
                res = merge_pr(int(pr_number), "squash")
                if not res.get("merged"):
                    return {
                        "executed": False,
                        "error": res.get("error", "merge failed"),
                        "deploy_pending": False,
                    }
                # Pin the deploy to the EXACT approved merge commit (no ride-along of
                # later main commits without a fresh approval).
                merge_sha = res.get("sha") or ""
                logger.info(
                    "codex_promote: merged PR #%s sha=%s — flagging deploy_pending",
                    pr_number,
                    merge_sha[:7],
                )
                # Close the delivered Codex task + its source backlog task so the
                # autonomous scheduler's queue_depth gate frees up. Without this a
                # merged task stays 'in_progress' forever and keeps counting as
                # "Codex busy" — after ~2 deliveries the loop self-throttles to a halt
                # (the host worker, run-codex-task.sh, never marks the source done; the
                # ONLY place a Codex task legitimately becomes 'completed' is here, on a
                # human-approved merge). Match the delegation row by the PR number the
                # worker stashed in metadata.codex_pr, then close its source task too.
                try:
                    from database import get_db_cursor as _gdc

                    with _gdc(commit=True) as (_cpc, _cpcur):
                        _cpcur.execute(
                            "UPDATE unified_tasks SET status='completed', updated_at=now() "
                            "WHERE delegation_args->>'capability'='codex_task' "
                            "AND metadata->>'codex_pr' = %s AND status <> 'completed' "
                            "RETURNING id",
                            (str(int(pr_number)),),
                        )
                        _done = [str(_r["id"]) for _r in _cpcur.fetchall()]
                        if _done:
                            _cpcur.execute(
                                "UPDATE unified_tasks SET status='completed', updated_at=now() "
                                "WHERE status NOT IN ('completed', 'cancelled') "
                                "AND delegation_args->>'codex_queued_delegate_id' = ANY(%s)",
                                (_done,),
                            )
                    logger.info(
                        "codex_promote: closed Codex task(s) %s for merged PR #%s",
                        _done,
                        pr_number,
                    )
                except Exception as _cp_done_err:
                    logger.warning(
                        "codex_promote: task completion writeback failed (non-fatal): %s",
                        _cp_done_err,
                    )
                return {
                    "executed": True,
                    "merged": True,
                    "pr_number": int(pr_number),
                    "module": module,
                    "merge_sha": merge_sha,
                    "deploy_pending": True,
                }
            except Exception as cp_err:
                logger.error("codex_promote execution failed: %s", cp_err)
                return {"executed": False, "error": str(cp_err)}

        elif action_type.startswith("compliance_fix_"):
            # Approved compliance fix — resume the apply pipeline from stage 3 (dry-run)
            scan_id = data.get("scan_id")
            rule_id = data.get("rule_id")
            user_id = data.get("requested_user_id") or 0
            if not scan_id or not rule_id:
                return {"executed": False, "error": "Missing scan_id or rule_id"}

            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from tools.security_network.compliance_service import (
                    apply_fix_approved,
                )

                result = apply_fix_approved(scan_id, rule_id, user_id)
                logger.info(f"Approved compliance fix #{item['id']} for {rule_id}: " f"success={result.get('success')}")
                return {
                    "executed": True,
                    "rule_id": rule_id,
                    "fix_success": result.get("success"),
                    "stages": result.get("stages", {}),
                }
            except Exception as comp_err:
                logger.error(f"Compliance fix execution failed: {comp_err}")
                return {"executed": False, "error": str(comp_err)}

        elif action_type == "linkedin_post":
            # Approved LinkedIn post — execute via archie_browser
            content = data.get("content", "")
            hashtags = data.get("hashtags", [])
            post_type = data.get("post_type", "personal")  # personal | company | creed | terry
            company_slug = data.get("company_slug", "kytran-empowerment-inc")
            # terry = separate LinkedIn login → its own browser profile (377).
            # All other accounts ride the Kytran session (342) and actor-switch.
            agent_id = data.get("browser_agent_id") or (377 if post_type == "terry" else 342)
            if not content:
                return {"executed": False, "error": "No content in action_data"}
            try:
                import re as _re
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                # Company slug: action_data > env var > default
                import os as _os

                if not company_slug:
                    company_slug = _os.getenv("LINKEDIN_COMPANY_SLUG", "kytran-empowerment-inc")

                # Clean content for LinkedIn — strip language prefixes, Markdown headers, bold
                def _clean_linkedin(text):
                    # Strip language prefix lines (🇨🇦 English: / ⚜️ Français québécois: / Translation in...)
                    text = _re.sub(
                        r"^[🇨🇦⚜️🇫🇷\s]*(?:English|Français québécois|Anglais|Translation in Québécois French)\s*:?\s*\n",
                        "",
                        text,
                        flags=_re.MULTILINE,
                    )
                    # Strip Markdown headers (### Title)
                    text = _re.sub(r"^#{1,6}\s+", "", text, flags=_re.MULTILINE)
                    # Strip **bold** markers
                    text = _re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=_re.DOTALL)
                    return text.strip()

                content = _clean_linkedin(content)
                # #4373 final publish-boundary guard — strip any model preamble/sign-off
                # ("Sure, here's the post:" …) that slipped past the draft-site sanitizer.
                from services.signal_content_sanitizer import clean_draft

                content = clean_draft(content, kind=post_type)
                if not content:
                    return {"executed": False, "error": "content empty after sanitize (#4373)"}

                # S6-P1-8b: idempotency. A cold post can take >180s; a timed-out + retried
                # post could double-publish. Compute a stable key (the calendar release
                # precomputes it; fall back to content+account for ad-hoc posts), pre-check
                # the publish ledger, and pass the key to the sidecar. Flag-gated by
                # platform_settings signal:idempotency_recovery_enabled (default on).
                _idem_enabled = True
                _idem_key = data.get("idempotency_key")
                _scheduled_post_id = data.get("scheduled_post_id")
                _idem_meta = None
                try:
                    from db import get_db as _gdb
                    from services import signal_accounts as _sa

                    _ic = _gdb()
                    _icur = _ic.cursor()
                    try:
                        _icur.execute(
                            "SELECT value FROM platform_settings WHERE key=%s",
                            ("signal:idempotency_recovery_enabled",),
                        )
                        _row = _icur.fetchone()
                        if _row and str(_row[0]).strip().lower() in ("false", "0", "off", "no"):
                            _idem_enabled = False
                        if _idem_enabled and not _idem_key:
                            _acct = _sa.post_type_to_account(post_type) or post_type
                            _idem_key = _sa.idempotency_key_for(_acct, post_type, content, _scheduled_post_id)
                        if _idem_enabled and _idem_key:
                            _icur.execute(
                                "SELECT post_url FROM linkedin_post_log "
                                "WHERE idempotency_key=%s AND status='posted' LIMIT 1",
                                (_idem_key,),
                            )
                            _prior = _icur.fetchone()
                            if _prior:
                                logger.info("LinkedIn post idempotent-skip — %s already published", _idem_key)
                                return {
                                    "executed": True,
                                    "idempotent_skip": True,
                                    "result": {"success": True, "post_url": _prior[0]},
                                    "error": None,
                                }
                    finally:
                        _icur.close()
                        _ic.close()
                    if _idem_enabled:
                        _idem_meta = {"post_type": post_type, "scheduled_post_id": _scheduled_post_id}
                except Exception as _ie:
                    logger.warning("idempotency setup/pre-check failed (non-fatal): %s", _ie)

                if post_type == "creed":
                    skill = "linkedin_creed_post"
                elif post_type == "company":
                    skill = "linkedin_company_post"
                elif post_type == "group":
                    skill = "linkedin_group_post"
                else:
                    skill = "linkedin_post"
                params = {"content": content, "hashtags": hashtags}
                if post_type == "creed":
                    # Creed slug: action_data > env var > numeric default
                    creed_slug = data.get("company_slug") or _os.getenv("LINKEDIN_CREED_SLUG", "115977300")
                    params["company_slug"] = creed_slug
                    company_slug = creed_slug
                elif post_type == "company":
                    params["company_slug"] = company_slug
                elif post_type == "group":
                    # Group id rides action_data (company_slug passthrough) > env.
                    # NOT the company_slug var (its default is the KE Inc. slug).
                    params["group_id"] = (
                        data.get("group_id")
                        or data.get("company_slug")
                        or _os.getenv("LINKEDIN_WTF_GROUP_ID", "37040054")
                    )

                # #5627 PRE-FLIGHT: this executor is THE choke point — there are six
                # independent producers of linkedin_post approvals (signal_calendar_service,
                # signal_dispatch x2, creed marketing_routes, agent_jobs x2), so gating any
                # single producer leaves the others open. Gate here instead, per decision
                # #953 ("gate the CHOKE POINT, never per-caller"). If the posting profile is
                # KNOWN dead, don't burn a 240s browser run to rediscover it — fail fast with
                # an honest reason instead of the misleading "Could not find feed share box".
                # Fail-OPEN on any lookup error: a health-read bug must never block posting.
                try:
                    from services import browser_session_service as _bss

                    if _bss.is_known_logged_out(agent_id, "linkedin"):
                        logger.warning(
                            "[linkedin] agent %s posting profile is known logged out — "
                            "refusing to post (%s). Re-auth via DHQ → S.I.G.N.A.L. → 🔐 Session.",
                            agent_id,
                            skill,
                        )
                        return {
                            "executed": False,
                            "error": (
                                f"LinkedIn posting profile for agent {agent_id} is logged out "
                                f"(/profiles/{agent_id}-linkedin). Re-auth via DHQ → S.I.G.N.A.L. "
                                f"→ 🔐 Session (noVNC headed login). A Cookie-Editor import only "
                                f"fixes the READ path, not posting (#3948)."
                            ),
                            "profile_logged_out": True,
                        }
                except Exception as _pf_err:
                    logger.debug("[linkedin] pre-flight health check failed (fail-open): %s", _pf_err)

                # #4327: a cold LinkedIn post on the hub can take 180s+; 120s was
                # shorter than the post itself, so it timed out and (with the old
                # unconditional executed:True) was marked done without publishing.
                # 240s stays within the _process_approval_queue batch deadline.
                result = run_skill_sync(
                    skill,
                    params,
                    agent_id=agent_id,
                    timeout_s=240,
                    idempotency_key=_idem_key if _idem_enabled else None,
                    post_metadata=_idem_meta,
                )

                # #5627 FEEDBACK: an actual posting attempt that lands on the login wall is
                # the HIGHEST-authority evidence the platform ever gets that a profile is
                # dead — far better than a 4-hourly read probe. It was being dropped on the
                # floor: five real failures on 2026-08-15 wrote NOTHING to browser_sessions,
                # so the #1831 release guard stayed blind and kept releasing all day. Feed it
                # back so the FIRST failure pauses every producer, not the twentieth.
                if result.get("logged_out"):
                    try:
                        from services import browser_session_service as _bss

                        _bss.record_probe(
                            agent_id,
                            "linkedin",
                            ok=False,
                            reason=f"{skill} landed on a login/authwall during a real post",
                            logged_out=True,
                        )
                        logger.warning("[linkedin] agent %s flipped stale from a real posting attempt", agent_id)
                    except Exception as _fb_err:
                        logger.debug("[linkedin] logout feedback failed (best-effort): %s", _fb_err)

                # Harden company/creed: the multi-stage actor-switch (share box →
                # settings → actor toggle → select page → Save → Done) is transiently
                # flaky — a stage selector can miss on first load (observed live: the
                # KE Inc. post failed once then succeeded on retry). Retry ONCE on
                # failure. Duplicate-safe: the skill returns success only AFTER the
                # Post click; every failure path raises BEFORE any post is created.
                # #5627: never retry a LOGGED-OUT failure. The retry exists for a flaky
                # actor-switch stage, not for a dead session — on a login wall it just
                # doubles the failures and the wasted browser time (240s each).
                if not result.get("success") and result.get("logged_out"):
                    logger.warning(
                        "linkedin %s post failed on a login wall — skipping actor-switch retry",
                        post_type,
                    )
                elif not result.get("success") and post_type in ("company", "creed"):
                    logger.warning(
                        "linkedin %s post failed (%s) — retrying actor-switch once",
                        post_type,
                        result.get("error") or result.get("_status"),
                    )
                    result = run_skill_sync(
                        skill,
                        params,
                        agent_id=agent_id,
                        timeout_s=240,
                        idempotency_key=_idem_key if _idem_enabled else None,
                        post_metadata=_idem_meta,
                    )

                # Fresh connection after 120s browser skill — the caller's cur/conn
                # may have timed out server-side during execution, causing the log
                # write and commit to silently fail with the stale cursor.
                try:
                    from db import get_db as _get_db

                    _lc = _get_db()
                    _lcur = _lc.cursor()
                    try:
                        _lcur.execute(
                            """INSERT INTO linkedin_post_log
                                   (content, hashtags, post_type, company_slug, status, approval_id,
                                    post_url, agent_id, idempotency_key, scheduled_post_id, task_id, posted_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                               ON CONFLICT (idempotency_key, post_type, agent_id)
                                   WHERE idempotency_key IS NOT NULL DO NOTHING""",
                            (
                                content,
                                hashtags,
                                post_type,
                                company_slug if post_type in ("company", "creed") else None,
                                "posted" if result.get("success") else "failed",
                                item["id"],
                                # #3975: persist the published post URL the skill
                                # already returns (was dropped on the floor) so the
                                # #3964 comment monitor can auto-seed from it.
                                (result.get("post_url") or None),
                                agent_id,
                                # Key set only on SUCCESS → the UNIQUE dedup blocks a duplicate
                                # PUBLISH but never a legitimate retry of a genuinely-failed post.
                                (_idem_key if (_idem_enabled and result.get("success")) else None),
                                _scheduled_post_id,
                                result.get("_task_id"),
                            ),
                        )
                        _lc.commit()
                    finally:
                        _lcur.close()
                        _lc.close()
                except Exception as log_err:
                    logger.warning(f"linkedin_post_log write failed: {log_err}")

                logger.info("LinkedIn post approved and executed: success=%s", result.get("success"))

                # Auto first-comment to boost reach — fire-and-forget
                post_url = result.get("post_url", "")
                if result.get("success") and post_url:
                    try:
                        first_comment_text = (
                            "Thoughts? We're building this at kytranempowerment.com — "
                            "AI infrastructure that actually works. 🚀 Drop a comment below."
                        )
                        threading.Thread(
                            target=lambda: run_skill_sync(
                                "linkedin_first_comment",
                                {"post_url": post_url, "comment": first_comment_text},
                                agent_id=agent_id,
                                timeout_s=90,
                            ),
                            daemon=True,
                            name="linkedin-first-comment",
                        ).start()
                    except Exception as fc_err:
                        logger.warning("First comment thread failed: %s", fc_err)

                # #4327: report the real outcome. With _process_approval_queue now
                # honoring this flag, a timed-out / failed post is marked 'failed'
                # (not a false 'executed'). linkedin_post_log above already recorded
                # posted/failed + post_url, so verification stays truthful.
                return {
                    "executed": bool(result.get("success")),
                    "result": result,
                    "error": (
                        None if result.get("success") else (result.get("error") or "post did not publish within 240s")
                    ),
                }
            except Exception as li_err:
                logger.error(f"LinkedIn post execution failed: {li_err}")
                return {"executed": False, "error": str(li_err)}

        elif action_type == "linkedin_comment_reply":
            # #3992: approved reply to a comment on one of our posts. Threaded
            # reply via the comment DEEP-LINK (the only thing that renders the
            # specific comment thread to automation — KB #274178/#274179), using
            # the linkedin_comment_reply skill. Falls back to a top-level comment
            # (linkedin_comment) when no deep-link is present (older rows). The
            # skill's in-session verify gate keeps `executed` honest either way.
            comment_id = data.get("comment_id")
            comment_url = data.get("comment_url", "")
            post_url = data.get("post_url", "")
            reply = data.get("reply", "")
            # #4373 final publish-boundary guard — strip model preamble ("Sure, here's a
            # reply comment from Kytran Katarn:" was the live 1692 junk) + any hashtags.
            from services.signal_content_sanitizer import clean_draft

            reply = clean_draft(reply, kind="reply")
            comment_author = data.get("comment_author") or data.get("author") or ""
            # #5653 — FAIL LOUD, never default the identity. `or 342` silently posted as
            # Kytran's personal profile whenever browser_agent_id was missing/unresolvable,
            # which is a public identity crossover with no error anywhere. A LinkedIn action
            # that cannot prove which identity it belongs to must not happen at all.
            agent_id = data.get("browser_agent_id")
            if not agent_id:
                return {
                    "executed": False,
                    "error": (
                        f"identity_unresolved: no browser_agent_id on the {action_type} approval — "
                        "refusing to act under a defaulted identity (#5653)"
                    ),
                }
            if not reply or not (comment_url or post_url):
                return {"executed": False, "error": "reply and (comment_url or post_url) required"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                if comment_url:
                    result = run_skill_sync(
                        "linkedin_comment_reply",
                        {
                            "comment_url": comment_url,
                            "reply": reply,
                            "comment_author": comment_author,
                        },
                        agent_id=agent_id,
                        timeout_s=180,
                    )
                else:
                    result = run_skill_sync(
                        "linkedin_comment",
                        {"post_url": post_url, "comment": reply},
                        agent_id=agent_id,
                        timeout_s=120,
                    )
                # Fresh connection after the long browser call — the caller's
                # cursor may have gone stale (same class as linkedin_post).
                try:
                    from db import get_db as _get_db

                    _rc = _get_db()
                    _rcur = _rc.cursor()
                    try:
                        _rcur.execute(
                            "UPDATE linkedin_comments SET reply_status = %s WHERE id = %s",
                            (
                                "replied" if result.get("success") else "reply_failed",
                                comment_id,
                            ),
                        )
                        _rc.commit()
                    finally:
                        _rcur.close()
                        _rc.close()
                except Exception as _ue:
                    logger.warning(f"[comment-reply] status update failed: {_ue}")
                return {"executed": bool(result.get("success")), "result": result}
            except Exception as cr_err:
                logger.error(f"LinkedIn comment reply failed: {cr_err}")
                return {"executed": False, "error": str(cr_err)}

        elif action_type == "linkedin_reply":
            # Approved reply to a LinkedIn comment/message
            reply_to = data.get("reply_to", "")
            message = data.get("message", "")
            agent_id = data.get("browser_agent_id", 342)
            if not reply_to or not message:
                return {"executed": False, "error": "reply_to and message required"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                result = run_skill_sync(
                    "linkedin_reply", {"reply_to": reply_to, "message": message}, agent_id=agent_id, timeout_s=90
                )
                return {"executed": True, "result": result}
            except Exception as re_err:
                return {"executed": False, "error": str(re_err)}

        elif action_type == "linkedin_connect":
            # Approved connection request — execute via archie_browser
            profile_url = data.get("profile_url", "")
            note = data.get("note", "")
            agent_id = data.get("browser_agent_id", 342)
            if not profile_url:
                return {"executed": False, "error": "No profile_url in action_data"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                result = run_skill_sync(
                    "linkedin_connect",
                    {"profile_url": profile_url, "note": note},
                    agent_id=agent_id,
                    timeout_s=90,
                )
                # Update outreach queue status
                try:
                    cur.execute(
                        """UPDATE linkedin_outreach_queue
                           SET status = 'connect_requested', updated_at = NOW()
                           WHERE profile_url = %s""",
                        (profile_url,),
                    )
                    conn.commit()
                except Exception:
                    pass
                return {"executed": True, "result": result}
            except Exception as conn_err:
                logger.error(f"LinkedIn connect execution failed: {conn_err}")
                return {"executed": False, "error": str(conn_err)}

        elif action_type == "linkedin_like":
            # Approved reaction on a post (like/celebrate/support/love/insightful/funny).
            # Approval-gated engagement — fires only after a Telegram/tab Approve.
            post_url = data.get("post_url", "")
            reaction = data.get("reaction", "like")
            # #5653 — FAIL LOUD, never default the identity. `or 342` silently posted as
            # Kytran's personal profile whenever browser_agent_id was missing/unresolvable,
            # which is a public identity crossover with no error anywhere. A LinkedIn action
            # that cannot prove which identity it belongs to must not happen at all.
            agent_id = data.get("browser_agent_id")
            if not agent_id:
                return {
                    "executed": False,
                    "error": (
                        f"identity_unresolved: no browser_agent_id on the {action_type} approval — "
                        "refusing to act under a defaulted identity (#5653)"
                    ),
                }
            if not post_url:
                return {"executed": False, "error": "post_url required for linkedin_like"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                result = run_skill_sync(
                    "linkedin_like",
                    {"post_url": post_url, "reaction": reaction},
                    agent_id=agent_id,
                    timeout_s=120,
                )
                try:  # S7-P1-4b: close the engagement ledger row + bump the daily counter
                    from services.signal_engagement_service import record_executed

                    record_executed(post_url, agent_id, "like", bool(result.get("success")))
                except Exception:
                    pass
                return {
                    "executed": bool(result.get("success")),
                    "result": result,
                    "error": None if result.get("success") else (result.get("error") or "like did not register"),
                }
            except Exception as like_err:
                logger.error(f"LinkedIn like execution failed: {like_err}")
                return {"executed": False, "error": str(like_err)}

        elif action_type == "linkedin_comment":
            # Approved proactive comment on a post (any post). Approval-gated — fires
            # only after Approve. (Replies to comments on OUR posts use the dedicated
            # linkedin_comment_reply action via the comment monitor.)
            post_url = data.get("post_url", "")
            comment = data.get("comment", "")
            # #5653 — FAIL LOUD, never default the identity. `or 342` silently posted as
            # Kytran's personal profile whenever browser_agent_id was missing/unresolvable,
            # which is a public identity crossover with no error anywhere. A LinkedIn action
            # that cannot prove which identity it belongs to must not happen at all.
            agent_id = data.get("browser_agent_id")
            if not agent_id:
                return {
                    "executed": False,
                    "error": (
                        f"identity_unresolved: no browser_agent_id on the {action_type} approval — "
                        "refusing to act under a defaulted identity (#5653)"
                    ),
                }
            if not post_url or not comment:
                return {"executed": False, "error": "post_url and comment required for linkedin_comment"}
            try:
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                result = run_skill_sync(
                    "linkedin_comment",
                    {"post_url": post_url, "comment": comment},
                    agent_id=agent_id,
                    timeout_s=240,
                )
                try:  # S7-P1-4b: close the engagement ledger row + bump the daily counter
                    from services.signal_engagement_service import record_executed

                    record_executed(
                        post_url,
                        agent_id,
                        "comment",
                        bool(result.get("success")),
                        comment_url=result.get("comment_url"),
                    )
                except Exception:
                    pass
                return {
                    "executed": bool(result.get("success")),
                    "result": result,
                    "error": None if result.get("success") else (result.get("error") or "comment did not post"),
                }
            except Exception as cmt_err:
                logger.error(f"LinkedIn comment execution failed: {cmt_err}")
                return {"executed": False, "error": str(cmt_err)}

        elif action_type == "linkedin_comment_like":
            # Approved LIKE on a specific comment (cross-boost: Terry ↔ Kytran like
            # each other's comments). Approval-gated — fires only after Approve.
            comment_url = data.get("comment_url", "")
            # #5653 — FAIL LOUD, never default the identity. `or 342` silently posted as
            # Kytran's personal profile whenever browser_agent_id was missing/unresolvable,
            # which is a public identity crossover with no error anywhere. A LinkedIn action
            # that cannot prove which identity it belongs to must not happen at all.
            agent_id = data.get("browser_agent_id")
            if not agent_id:
                return {
                    "executed": False,
                    "error": (
                        f"identity_unresolved: no browser_agent_id on the {action_type} approval — "
                        "refusing to act under a defaulted identity (#5653)"
                    ),
                }
            if not comment_url:
                return {"executed": False, "error": "comment_url required for linkedin_comment_like"}
            try:
                # sys.path insert matches the established pattern of every sibling
                # handler here (linkedin_like/linkedin_comment above) — required for
                # platform_v2 service imports from the scheduler sidecar (KB #272154).
                import sys as _sys

                _sys.path.insert(0, "/app")
                from services.browser_service import run_skill_sync

                result = run_skill_sync(
                    "linkedin_comment_like",
                    {
                        "comment_url": comment_url,
                        "comment_author": data.get("comment_author", ""),
                        "comment_contains": data.get("comment_contains", ""),
                    },
                    agent_id=agent_id,
                    timeout_s=180,
                )
                try:  # close the engagement ledger row (keys on the comment urn)
                    from services.signal_engagement_service import record_executed

                    record_executed(comment_url, agent_id, "comment_like", bool(result.get("success")))
                except Exception:
                    pass
                return {
                    "executed": bool(result.get("success")),
                    "result": result,
                    "error": (
                        None if result.get("success") else (result.get("error") or "comment like did not register")
                    ),
                }
            except Exception as clike_err:
                logger.error(f"LinkedIn comment-like execution failed: {clike_err}")
                return {"executed": False, "error": str(clike_err)}

        else:
            # #5011 — an unhandled action type is a FAILURE, not a success.
            #
            # This returned {"skipped": True} with no 'executed' key, so it inherited the
            # `_ok = result.get("executed", True)` back-compat default (#4327) and the row was
            # written status='executed'. Consequence: an approval the OWNER PHYSICALLY TAPPED
            # silently did nothing while reporting success, and the row went terminal so it
            # could never be retried. Observed 2026-07-20 on queue #3201 (backup_before_deploy):
            # the handler existed on disk but the long-lived process had not reloaded it, the
            # tap was swallowed, and the only trace was a string buried in a JSONB column.
            #
            # The approval queue is the most trust-sensitive surface we have — it is where a
            # human is told their decision took effect. It must never claim success it did not
            # achieve. Returning executed=False records it as 'failed': visible in the Approvals
            # tab, and honest.
            logger.error(
                "[approval_queue] UNHANDLED action_type '%s' — approval recorded as FAILED. "
                "If a handler for this type was added recently, the running process may still "
                "be holding pre-deploy code; a restart is needed before it can execute.",
                action_type,
            )
            return {
                "executed": False,
                "skipped": True,
                "error": f"Unknown action type: {action_type} (no handler in the running process)",
                "reason": f"Unknown action type: {action_type}",
            }

    # ------------------------------------------------------------------
    # Dependabot Vulnerability Scan
    # ------------------------------------------------------------------

    def _run_dependabot_scan(self):
        """Agent Loop Job: Poll Dependabot alerts and triage pending repairs."""
        try:
            from tools.repair_bay.services.dependabot_service import (
                poll_and_ingest,
                sync_manifest_registry,
            )
            from tools.repair_bay.services.forge_triage import triage_pending_queue

            sync_manifest_registry()
            poll_result = poll_and_ingest()
            if not poll_result["success"]:
                logger.error("Dependabot poll failed: %s", poll_result.get("error"))
                return

            triage_result = triage_pending_queue()

            self._log_autonomy_action(
                action_type="dependabot_scan",
                details={
                    "new_alerts": poll_result.get("new_alerts", 0),
                    "dispatched": triage_result.get("dispatched", 0),
                    "escalated": triage_result.get("escalated", 0),
                    "dismissed": triage_result.get("dismissed", 0),
                },
                success=True,
            )
            logger.info(
                "Dependabot scan complete: %d new, %d dispatched, %d escalated",
                poll_result.get("new_alerts", 0),
                triage_result.get("dispatched", 0),
                triage_result.get("escalated", 0),
            )
        except Exception as e:
            logger.error("Dependabot scan job failed: %s", e)
            self._log_autonomy_action(
                action_type="dependabot_scan",
                details={"error": str(e)},
                success=False,
            )

    def _run_market_watch_cycle(self):
        """Agent Loop Job: M.A.R.K.E.T. autonomous trading cycle.

        Fires every 30 min during NYSE market hours (Mon-Fri 9:30am-4pm ET).
        Calls Market Watch run-cycle endpoint with service token auth.
        """
        try:
            import requests
            import os

            service_token = os.environ.get("ARCHIE_SERVICE_TOKEN", "")
            headers = {"Content-Type": "application/json"}
            if service_token:
                headers["Authorization"] = f"Bearer {service_token}"

            resp = requests.post(
                "http://100.64.0.10:8101/api/trading/run-cycle",  # Citadel/boston-2 mesh IP (market-watch migrated off outpost-us 2026-06)
                json={"source": "archie_dispatch", "dispatch_id": f"autonomy_{id(self)}"},
                headers=headers,
                timeout=600,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("skipped"):
                    logger.info("M.A.R.K.E.T. cycle skipped (dedup): %s", data.get("reason"))
                    return
                self._log_autonomy_action(
                    action_type="market_watch_cycle",
                    details={
                        "tickers_analyzed": data.get("tickers_analyzed", 0),
                        "trades_executed": data.get("trades_executed", 0),
                        "trades_skipped": data.get("trades_skipped", 0),
                        "positions_closed": data.get("positions_closed", 0),
                        "errors": data.get("errors", 0),
                        "portfolio_value": data.get("portfolio_value"),
                        "daily_pnl_pct": data.get("daily_pnl_pct"),
                        "dry_run": data.get("dry_run", False),
                    },
                    success=True,
                )
                logger.info(
                    "M.A.R.K.E.T. cycle: %d analyzed, %d executed, %d skipped, %d closed, P&L: %.2f%%",
                    data.get("tickers_analyzed", 0),
                    data.get("trades_executed", 0),
                    data.get("trades_skipped", 0),
                    data.get("positions_closed", 0),
                    data.get("daily_pnl_pct", 0),
                )
            elif resp.status_code == 503:
                logger.warning("M.A.R.K.E.T. cycle: trading disabled (kill switch)")
            else:
                logger.error("M.A.R.K.E.T. cycle failed: HTTP %d", resp.status_code)
                self._log_autonomy_action(
                    action_type="market_watch_cycle",
                    details={"error": f"HTTP {resp.status_code}"},
                    success=False,
                )
        except Exception as e:
            logger.error("M.A.R.K.E.T. cycle job failed: %s", e)
            self._log_autonomy_action(
                action_type="market_watch_cycle",
                details={"error": str(e)},
                success=False,
            )

    # Proactive Code Sentinel (Phase 5 — Task 3)
    # ------------------------------------------------------------------

    def _run_proactive_scan(self):
        """Proactive Code Sentinel scan — runs every 6h.

        Scans recently changed files, falls back to key platform files.
        Phase 4 hooks auto-create proposals from findings.
        """
        start = time.time()
        try:
            import subprocess

            # Get recently changed Python files (last 5 commits)
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~5"],
                    capture_output=True,
                    text=True,
                    cwd="/mnt/archie_brain",
                    timeout=10,
                )
                changed_files = [
                    f
                    for f in result.stdout.strip().split("\n")
                    if f.endswith(".py")
                    and f.startswith("platform_v2/")
                    and not f.startswith("platform_v2/tools/_deprecated")
                ]
            except Exception:
                changed_files = []

            # Fallback: key platform files on rotation
            if not changed_files:
                import hashlib
                from datetime import datetime

                key_files = [
                    "platform_v2/app.py",
                    "ai_bridge/bridge_dispatcher.py",
                    "ai_bridge/agent_loop.py",
                    "platform_v2/tools/consciousness/routes.py",
                    "platform_v2/tools/dev_hq/routes.py",
                    "platform_v2/tools/improvements/routes.py",
                    "ai_bridge/code_generation_engine.py",
                    "ai_bridge/improvement_chat.py",
                ]
                # Rotate: pick 2 files based on current day
                day_hash = int(
                    hashlib.md5(datetime.now().strftime("%Y-%m-%d").encode()).hexdigest()[:8],
                    16,
                )
                start_idx = day_hash % len(key_files)
                changed_files = [
                    key_files[start_idx % len(key_files)],
                    key_files[(start_idx + 1) % len(key_files)],
                ]

            # Limit to 3 files per run
            scan_files = changed_files[:3]

            scanned = 0
            for file_path in scan_files:
                try:
                    full_path = f"/mnt/archie_brain/{file_path}"
                    import os

                    if not os.path.exists(full_path):
                        continue

                    with open(full_path, "r") as f:
                        code_content = f.read()

                    # Use scan service's static analysis
                    import sys

                    sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from services.scan_service import static_analysis

                    analysis = static_analysis(code_content, file_path)
                    issues = analysis.get("issues", [])

                    if not issues:
                        continue

                    # Store scan + issues in DB
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)

                    cur.execute(
                        """
                        INSERT INTO code_scans (file_path, scan_type, issues_found,
                            security_issues, quality_score, scan_result, scanned_by)
                        VALUES (%s, 'proactive_scan', %s, %s, %s, %s, 'agent_loop')
                        RETURNING id
                        """,
                        (
                            file_path,
                            len(issues),
                            len([i for i in issues if i.get("type") == "security"]),
                            analysis.get("quality_score", 0),
                            json.dumps(analysis),
                        ),
                    )
                    scan_id = cur.fetchone()["id"]

                    for issue in issues:
                        cur.execute(
                            """
                            INSERT INTO code_issues (scan_id, file_path, line_number,
                                issue_type, severity, message, suggestion)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                scan_id,
                                file_path,
                                issue.get("line"),
                                issue.get("type", "quality"),
                                issue.get("severity", "medium"),
                                issue.get("message", ""),
                                issue.get("suggestion", ""),
                            ),
                        )
                    conn.commit()
                    cur.close()
                    conn.close()

                    # Phase 4 pipeline hook
                    from services.scan_pipeline import process_scan_results

                    process_scan_results(scan_id, issues, file_path)

                    # Wire findings into Repair Bay proposal pipeline
                    try:
                        from services.audit_pipeline import process_audit_findings

                        # Map scan issue format → audit finding format
                        # scan: {type, severity(high/medium/low), message, suggestion, line}
                        # audit: {code, severity(red/yellow/info), file, detail}
                        _severity_map = {
                            "high": "red",
                            "critical": "red",
                            "medium": "yellow",
                            "low": "info",
                        }
                        audit_issues = []
                        for _issue in issues:
                            _sev = _severity_map.get(str(_issue.get("severity", "")).lower(), "info")
                            audit_issues.append(
                                {
                                    "code": _issue.get("type", "quality"),
                                    "severity": _sev,
                                    "file": file_path,
                                    "detail": _issue.get("message", "")
                                    + (f" (line {_issue['line']})" if _issue.get("line") else "")
                                    + (f" — Suggestion: {_issue['suggestion']}" if _issue.get("suggestion") else ""),
                                }
                            )

                        # Derive module name from file path
                        # e.g. platform_v2/tools/foo/bar.py → foo
                        # e.g. ai_bridge/agent_loop.py → [ai_bridge]
                        _parts = file_path.replace("\\", "/").split("/")
                        if "tools" in _parts:
                            _tidx = _parts.index("tools")
                            _module = _parts[_tidx + 1] if len(_parts) > _tidx + 1 else "unknown"
                        elif len(_parts) >= 2:
                            _module = f"[{_parts[0]}]"
                        else:
                            _module = file_path

                        result = process_audit_findings(_module, audit_issues)
                        if result.get("proposals_created", 0) > 0:
                            logger.info(
                                "Proactive scan → audit pipeline: %d proposals created for %s",
                                result["proposals_created"],
                                file_path,
                            )
                    except Exception as _pipe_err:
                        logger.warning(
                            "Proactive scan audit pipeline failed for %s: %s",
                            file_path,
                            _pipe_err,
                        )

                    scanned += 1

                except Exception as scan_err:
                    logger.warning(f"Proactive scan failed for {file_path}: {scan_err}")

            duration_ms = int((time.time() - start) * 1000)
            if scanned > 0:
                logger.info(f"Proactive scan: {scanned}/{len(scan_files)} files scanned " f"({duration_ms}ms)")
                # Auto-heal: route new proposals through proposal_regen first so an
                # agent generates a real code fix before F.O.R.G.E. reviews it.
                # auto_queue_deploy=True in callback_data chains to deploy_approve_gate
                # once code_changes is populated and status is ready_for_review.
                try:
                    import json as _json_ah
                    import sys as _sys

                    _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from database import get_db_cursor as _gdc

                    with _gdc() as (_ac, _acur):
                        _acur.execute(
                            """SELECT id, title, description, category, metadata
                               FROM improvement_proposals
                               WHERE status = 'pending'
                               AND risk_level IN ('low', 'medium')
                               AND proposed_at > NOW() - INTERVAL '10 minutes'
                               ORDER BY proposed_at DESC LIMIT 20"""
                        )
                        new_proposals = _acur.fetchall()

                    auto_queued = 0
                    for _p in new_proposals:
                        pid = _p["id"]
                        try:
                            _meta = _p.get("metadata") or {}
                            if isinstance(_meta, str):
                                try:
                                    _meta = _json_ah.loads(_meta)
                                except Exception:
                                    _meta = {}
                            _regen_prompt = (
                                f"Generate a code fix for proposal #{pid}: {_p['title']}.\n"
                                f"Issue: {_p.get('description', '')}\n"
                                f"File: {_meta.get('file_path', 'unknown')}, "
                                f"line {_meta.get('line_number', 'N/A')}\n"
                                f"Fix suggestion: {_meta.get('suggestion', _meta.get('fix_suggestion', ''))}\n"
                                f"Provide the exact code fix as a unified diff."
                            )
                            _cap = "security" if _p.get("category") == "security" else "code"
                            with _gdc(commit=True) as (_bc, _bcur):
                                _bcur.execute(
                                    "UPDATE improvement_proposals SET status='approved' "
                                    "WHERE id=%s AND status='pending'",
                                    (pid,),
                                )
                                _bcur.execute(
                                    """INSERT INTO dispatch_pending_queue
                                        (capability, model_needed, model_type, prompt,
                                         agent_name, agent_id, module_id, source_product,
                                         requested_by, priority, callback_type, callback_data)
                                       VALUES (%s,'mistral:7b','llama',%s,'F.O.R.G.E.',
                                               NULL,'repair_bay','archie_platform',
                                               'proactive_scan',6,'proposal_regen',%s)""",
                                    (
                                        _cap,
                                        _regen_prompt,
                                        _json_ah.dumps(
                                            {
                                                "proposal_id": pid,
                                                "agent_name": "F.O.R.G.E.",
                                                "auto_queue_deploy": True,
                                            }
                                        ),
                                    ),
                                )
                            auto_queued += 1
                        except Exception as _ae:
                            logger.debug("auto-heal regen queue #%s: %s", pid, _ae)

                    if auto_queued:
                        logger.info(
                            "Proactive scan auto-heal: queued %d/%d proposals for regen",
                            auto_queued,
                            len(new_proposals),
                        )
                except Exception as _he:
                    logger.warning("Proactive scan auto-heal failed: %s", _he)

        except Exception as e:
            logger.error(f"Proactive scan job failed: {e}")

    def _run_dependency_audit(self):
        """Dependency CVE audit — runs every 6h alongside proactive scan.

        Checks pip packages for known vulnerabilities, stores findings
        in Repair Bay's code_scans/code_issues tables, alerts on critical.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.scan_service import (
                audit_dependencies,
                store_dependency_findings,
            )

            findings = audit_dependencies()
            if not findings:
                logger.debug("Dependency audit: no findings")
                return

            store_dependency_findings(findings)

            # Alert on critical/high
            critical = [f for f in findings if f["severity"] in ("critical", "high")]
            if critical:
                self._send_telegram(
                    "\u26a0\ufe0f *Dependency Audit*\n\n"
                    f"*{len(critical)}* critical/high CVEs found:\n"
                    + "\n".join(f"- {f['package']}=={f['version']}: {f['vuln_id']}" for f in critical[:5])
                    + "\n\n[View in Repair Bay]"
                    "(http://192.168.1.200:3000/tools/repair-bay)"
                )

            duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "Dependency audit: %d findings (%d critical/high) in %dms",
                len(findings),
                len(critical),
                duration_ms,
            )

        except Exception as e:
            logger.error("Dependency audit failed: %s", e)

    # ------------------------------------------------------------------
    # S.P.E.C.T.R.A. Dispatch Misroute Audit (Project #272 / Task #2105)
    # ------------------------------------------------------------------

    def _run_misroute_audit(self):
        """Nightly dispatch misroute audit owned by S.P.E.C.T.R.A.

        Delegates the scan to ``services.misroute_audit_service.run_misroute_audit``
        (single source of truth), then surfaces results via:
          * one ``autonomy_loop_log`` row (always, regardless of severity)
          * one ``system_notifications`` row when severity >= 'warning'
          * one Telegram alert when severity == 'error'

        The MCP tool ``mcp__archie__run_misroute_audit`` wraps the same
        service function so Kytran can invoke it on demand.
        """
        start = time.time()
        severity = "info"
        result = None
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.misroute_audit_service import (
                format_alert_message,
                run_misroute_audit,
            )

            result = run_misroute_audit(window_hours=24)
            severity = result["severity"]
            metrics = result["summary_metrics"]
            duration_ms = int((time.time() - start) * 1000)

            # Always log the cycle so the Dev HQ routing dashboard (#2110)
            # has a timeline to render.
            self._log_cycle(
                job_name="spectra_misroute_audit",
                items_processed=result["anomaly_count"],
                items_failed=metrics["high_failure_pairs"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "reasons": result.get("reasons", []),
                    "window_hours": result["window_hours"],
                    "finding_sizes": {k: len(v) for k, v in result["findings"].items()},
                },
            )

            # Surface on warning or worse. Info-level runs are silent.
            if severity in ("warning", "error"):
                body = format_alert_message(result)
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"S.P.E.C.T.R.A. — {severity} in dispatch routing",
                            body,
                            "spectra",
                            "high" if severity == "error" else "normal",
                            "🛰️",
                            "/tools/department-hq#dispatch",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as notify_err:
                    logger.warning(
                        "Misroute audit: system_notifications insert failed: %s",
                        notify_err,
                    )

            # Telegram only on 'error'. Warnings stay in the notifications
            # tray so they don't spam the phone.
            if severity == "error":
                try:
                    self._send_telegram(format_alert_message(result))
                except Exception as tg_err:
                    logger.warning("Misroute audit: Telegram dispatch failed: %s", tg_err)

            logger.info(
                "S.P.E.C.T.R.A. misroute audit: severity=%s anomalies=%d in %dms",
                severity,
                result["anomaly_count"],
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("S.P.E.C.T.R.A. misroute audit failed: %s", e)
            try:
                self._log_cycle(
                    job_name="spectra_misroute_audit",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # S.P.E.C.T.R.A. → Audit Pipeline adapter (Project #272 / Task #2186)
    # ------------------------------------------------------------------

    def _run_misroute_to_proposal_adapter(self):
        """Nightly adapter: convert misroute findings into audit proposals.

        Runs 15 min after ``_run_misroute_audit``. Delegates the scan +
        conversion + pipeline call to
        ``services.misroute_to_proposal_adapter.run`` (single source of
        truth), then logs one ``autonomy_loop_log`` row for the Dev HQ
        routing dashboard (#2110) to render a timeline.

        No-op path stays silent. Any proposals created are automatically
        routed into the approval queue by ``audit_pipeline._create_audit_proposal``.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.misroute_to_proposal_adapter import run as run_adapter

            result = run_adapter(window_hours=24)
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="misroute_to_proposal_adapter",
                items_processed=result.get("issues_generated", 0),
                items_failed=0,
                duration_ms=duration_ms,
                details={
                    "input_anomalies": result.get("input_anomalies", 0),
                    "audit_severity": result.get("audit_severity"),
                    "proposals_created": result.get("proposals_created", 0),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "issues_by_code": result.get("issues_by_code", {}),
                    "window_hours": result.get("window_hours"),
                },
            )

            logger.info(
                "misroute_to_proposal_adapter: anomalies=%d issues=%d proposals=%d in %dms",
                result.get("input_anomalies", 0),
                result.get("issues_generated", 0),
                result.get("proposals_created", 0),
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("misroute_to_proposal_adapter failed: %s", e)
            try:
                self._log_cycle(
                    job_name="misroute_to_proposal_adapter",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # C.R.E.E.D. accounting self-audit — "use our own tools" (net-new)
    # ------------------------------------------------------------------

    def _run_creed_accounting_audit(self):
        """Daily C.R.E.E.D. accounting self-audit.

        Delegates the actual invariant checks to
        ``services.creed_accounting_audit.run_accounting_audit`` (pure,
        read-only, side-effect-free — safe to call from tests). This job is
        the ONLY caller that alerts: on ``ok=False`` it (a) files a C.R.E.E.D.
        governance event (transparency pillar — the platform holding its own
        token/welfare/carbon accounting to the standard it audits everyone
        else by) and (b) sends an A.R.C.H.I.E. Telegram advisory. Detection
        only — never fixes anything, so accounting bugs (fabricated cloud
        carbon, undercounted tokens, agents missing budget/welfare rows,
        unattributed cloud spend) can't silently regress unnoticed.

        Gated by ``platform_settings work:creed_accounting_audit:enabled``
        (default ON, fail-open) via ``services.work_control_service``.
        """
        start = time.time()
        try:
            from services.work_control_service import is_enabled

            if not is_enabled("creed_accounting_audit", default=True):
                self._log_cycle(
                    job_name="creed_accounting_audit",
                    items_processed=0,
                    items_failed=0,
                    duration_ms=int((time.time() - start) * 1000),
                    details={"skipped": "disabled via work_control"},
                )
                return
        except Exception:
            pass  # fail-open — never let a work-control glitch skip the audit

        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.creed_accounting_audit import run_accounting_audit

            result = run_accounting_audit()
            findings = result.get("findings", [])
            duration_ms = int((time.time() - start) * 1000)

            if not result.get("ok", True):
                summary = "; ".join(f"{f['code']} ({f['count']})" for f in findings)

                # (a) C.R.E.E.D. governance event — transparency pillar.
                try:
                    from services.creed_emit import emit_event

                    emit_event(
                        category="transparency",
                        severity="warning",
                        description=(
                            f"C.R.E.E.D. accounting self-audit found {len(findings)} "
                            f"invariant violation(s): {summary}"
                        ),
                        event_type="accounting_self_audit",
                        agent_name="A.R.C.H.I.E.",
                        module="Accounting Audit",
                        metadata={"findings": findings},
                    )
                except Exception as emit_err:
                    logger.warning("creed_accounting_audit: creed_emit failed: %s", emit_err)

                # (b) A.R.C.H.I.E. Telegram advisory.
                try:
                    from services.telegram_service import send_info

                    body = "\n".join(f"- {f['code']} ({f['count']}): {f['detail']}" for f in findings)
                    send_info(
                        "C.R.E.E.D. accounting self-audit — drift detected",
                        body,
                    )
                except Exception as tg_err:
                    logger.warning("creed_accounting_audit: telegram send failed: %s", tg_err)

            self._log_cycle(
                job_name="creed_accounting_audit",
                items_processed=len(findings),
                items_failed=0 if result.get("ok") else len(findings),
                duration_ms=duration_ms,
                details={"ok": result.get("ok"), "findings": findings},
            )
            logger.info(
                "creed_accounting_audit: ok=%s findings=%d in %dms",
                result.get("ok"),
                len(findings),
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("creed_accounting_audit failed: %s", e)
            try:
                self._log_cycle(
                    job_name="creed_accounting_audit",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e)[:200],
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Archie-as-delegate worker (Project #276 / Task #2209)
    # ------------------------------------------------------------------

    # Per-capability timeouts for delegated task execution. The dispatcher
    # has its own 300s budget (CAPABILITY_TIMEOUTS in department_dispatcher.py);
    # these are the OUTER ceiling that keeps the worker alive when any layer
    # below hangs. Saw 7+ hour outage on 2026-05-03 when deploy_vps rsync
    # stalled and APScheduler max_instances=1 + coalesce=True locked us out.
    _DELEGATE_CAPABILITY_TIMEOUTS = {
        "deploy_vps": 600,
        "deploy_static": 600,
        # documentation: heavy 7B doc-gen, 250-530s on CPU outpost nodes.
        # Dispatcher allows 600s (CAPABILITY_TIMEOUTS); +60s worker buffer.
        # Was false-blocking at the 360s default (tasks #3549/#3551).
        "documentation": 660,
        # research / compliance / code / analyze: heavy open-ended 7B work,
        # same profile as documentation. Dispatcher allows 600s
        # (CAPABILITY_TIMEOUTS); +60s worker buffer. Were false-blocking at
        # the 360s default (tasks #3624-#3630, 2026-06-01, mistake #269999).
        "research": 660,
        "compliance": 660,
        "code": 660,
        "analyze": 660,
        # translate: heavy 7B FR/multilingual generation (R.O.S.E.T.T.A.).
        # Dispatcher allows 600s (CAPABILITY_TIMEOUTS); +60s worker buffer.
        # Was false-blocking at the 360s default — the node finished a FR
        # translation at ~497s but the worker had already given up at 360s
        # and marked the task blocked (#3967, 2026-06-10; status != artifact).
        "translate": 660,
        # translation_coverage_scan: git-hook triggers now run a SCOPED scan
        # (seconds), but a manual/broad delegate runs the full multi-pass scan.
        # 900s backstop so a broad scan can't false-block at the 360s default.
        "translation_coverage_scan": 900,
        # A bare run_qa_suite (no suite_id) runs ALL ~75 active suites and
        # aggregates — a full health scan, ~400-600s. Single-suite runs finish
        # in seconds; this generous ceiling only matters for the full scan,
        # which the concurrent worker carries in the background (one of N slots).
        "run_qa_suite": 1200,
        "run_misroute_audit": 120,
        "run_misroute_to_proposal_adapter": 120,
        "check_dep_drift": 60,
        "health_check": 30,
        "check_platform_health": 30,
    }
    _DELEGATE_DEFAULT_TIMEOUT_SECS = 360  # dispatcher 300s + 60s buffer

    # Concurrency: how many delegated tasks run in parallel. The old worker
    # was serial (pool max_workers=1), so one slow 7B task blocked everything
    # behind it. The DB pool (maxconn=50) and the cluster's own welfare/queue
    # gating make a modest fan-out safe. Env-tunable; dial down if the cluster
    # saturates under local_only escalation.
    _DELEGATE_CONCURRENCY = int(os.getenv("DELEGATE_WORKER_CONCURRENCY", "4"))
    # How long one invocation blocks collecting finishers before returning and
    # letting the next 30s fire top up freed slots. Slightly under the 30s
    # cadence so cycles never pile up under max_instances=1. Tasks still
    # running at the budget roll into the carry-over list (NOT marked blocked —
    # their real per-capability deadline still applies).
    _DELEGATE_CYCLE_BUDGET_SECS = float(os.getenv("DELEGATE_WORKER_CYCLE_BUDGET_SECS", "25"))

    def _run_agent_kb_review(self):
        """#3534 Phase 3: C.O.D.E.X. reviews pending agent-proposed KB writes.

        Dispatches each quarantined ``source_type='agent_proposed'`` /
        ``review_status='pending'`` entry to C.O.D.E.X. (via DHQ) to promote
        (review_status='approved') or reject. No-op when there are none.
        """
        try:
            from services.agent_kb_service import auto_review_pending_writes

            auto_review_pending_writes(limit=20)
        except Exception as exc:
            logger.warning("[agent_kb_review] job failed: %s", exc)

    def _run_node_auto_provision(self):
        """#3732: stock a newly enrolled fleet node's recommended warm-set.

        Diffs each approved+online wizard node's hardware recommendation
        (services.node_provisioning) against the models it already reports, and
        queues the gap into the OTA ``mesh_sync_log`` pull queue. Idempotent
        (fully-stocked nodes are no-ops) and gated behind platform_settings
        ``node_auto_provision_enabled`` (default off). No-op until enabled.
        """
        try:
            from services.node_auto_provision import auto_provision_nodes

            res = auto_provision_nodes(dry_run=False, max_nodes=2)
            if res.get("provisioned"):
                logger.info("[node_auto_provision] %s", res)
        except Exception as exc:
            logger.warning("[node_auto_provision] job failed: %s", exc)

    def _run_fleet_backlog_runner(self):
        """Promote a few pending unified_tasks to the fleet (Phase 3, decision #676).

        DEFAULT OFF — dormant until enabled in the DHQ Autonomy tab (Backlogs).
        Keeps the delegated queue shallow (refills toward TARGET) so a large
        backlog drains steadily via delegate_task_worker (3/cycle) + dispatcher
        welfare-gating, instead of flooding the fleet. Fail-safe: any error is a
        no-op for that cycle.
        """
        import time as _t

        t0 = _t.time()
        try:
            from services.work_control_service import is_enabled

            if not is_enabled("fleet_backlog_runner", default=False):
                return
        except Exception:
            return  # control plane unavailable → do nothing

        TARGET = 5  # keep ~5 tasks queued for the fleet
        MAX_PROMOTE = 3  # never promote more than this per cycle
        # Fleet LLM agents produce analysis, not commits — promoting bugfix/implementation
        # lets a 7B falsely 'complete' engineering/hardware tasks (audit 2026-08-17, KB #290290).
        CAP_MAP = {
            "research": "research",
            "documentation": "documentation",
            "review": "analyze",
            "testing": "analyze",
        }
        promoted = 0
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "SELECT COUNT(*) AS n FROM unified_tasks "
                    "WHERE delegation_source IS NOT NULL AND status = 'pending'"
                )
                queued = cur.fetchone()["n"]
                slots = max(0, min(TARGET - queued, MAX_PROMOTE))
                if slots > 0:
                    # AGENT MOBILITY PROFILE: when news/platform is active, drain
                    # that profile's product backlog first (news → WTF/watch/CREED
                    # projects; platform → the rest). auto = pure priority order.
                    try:
                        from services.fleet_dispatch_profile import (
                            get_dispatch_mode,
                            is_priority_project,
                        )

                        _mode = get_dispatch_mode()
                    except Exception:
                        _mode = "auto"
                    _pool = slots * 6 if _mode != "auto" else slots
                    _eligible_types = tuple(CAP_MAP.keys())
                    cur.execute(
                        "SELECT ut.id, ut.title, ut.task_type, p.name AS project_name "
                        "FROM unified_tasks ut "
                        "LEFT JOIN unified_projects p ON p.id = ut.project_id "
                        "WHERE ut.delegation_source IS NULL AND ut.status = 'pending' "
                        "AND ut.task_type IS NOT NULL "
                        "AND lower(ut.task_type) IN %s "
                        "ORDER BY ut.priority DESC, ut.created_at ASC LIMIT %s",
                        (_eligible_types, _pool),
                    )
                    _cands = cur.fetchall()
                    if _mode != "auto" and _cands:
                        # Stable split keeps priority/created order within each
                        # group; profile-matching projects promote first.
                        _tagged = [(r, is_priority_project(r.get("project_name"), _mode)) for r in _cands]
                        _cands = [r for r, p in _tagged if p] + [r for r, p in _tagged if not p]
                        logger.info(
                            "[FleetBacklogRunner] profile=%s: %d/%d candidate task(s) match profile",
                            _mode,
                            sum(1 for _, p in _tagged if p),
                            len(_tagged),
                        )
                    for r in _cands[:slots]:
                        cap = CAP_MAP.get((r["task_type"] or "").lower())
                        if not cap:
                            # Not fleet-delegable — never default to 'research' (KB #290290)
                            continue
                        args = json.dumps({"capability": cap, "reason": (r["title"] or "")[:300]})
                        cur.execute(
                            "UPDATE unified_tasks SET delegation_source = 'automation', "
                            "delegation_args = %s WHERE id = %s AND delegation_source IS NULL",
                            (args, r["id"]),
                        )
                        promoted += cur.rowcount
        except Exception as e:
            logger.warning("[FleetBacklogRunner] failed: %s", e)
            self._log_cycle("fleet_backlog_runner", 0, 1, int((_t.time() - t0) * 1000), error_message=str(e)[:200])
            return
        if promoted:
            logger.info("[FleetBacklogRunner] promoted %d task(s) to the fleet", promoted)
        self._log_cycle("fleet_backlog_runner", promoted, 0, int((_t.time() - t0) * 1000))

    def _run_delegation_triage(self):
        """#4350: daily sweep of STALE blocked documentation delegations.

        Delegates to delegation_service.triage_blocked_delegations() — clears
        blocked doc tasks whose PR is already documented in the KB, re-queues
        undocumented ones once. Fail-safe; logs only when it acts.
        """
        try:
            from services.delegation_service import triage_blocked_delegations

            res = triage_blocked_delegations()
            if res.get("cleared") or res.get("requeued"):
                logger.info("[DelegationTriage] %s", res)
        except Exception as e:
            logger.error("delegation_triage failed: %s", e)

    def _run_delegate_task_worker(self):
        """Pick up pending delegated tasks and execute via OrchestrationEngine.

        Polls ``unified_tasks`` for rows with ``delegation_source IS NOT
        NULL`` AND ``status = 'pending'``. Per cycle, claims up to 3
        tasks to avoid starving other agent-loop jobs. Each claimed task
        is flipped to ``in_progress`` before execution; on completion or
        failure, status + a ``work_notes`` row are written.

        Per-task timeout shield: each ``execute_delegated_task`` call runs
        in a worker-owned thread pool with a per-capability timeout. If a
        layer below hangs (rsync, Playwright cold-start, model load), the
        future bails out, the task is marked blocked, and the worker
        keeps running. Without this shield, APScheduler's
        ``max_instances=1, coalesce=True`` permanently freezes the job.

        Logs one ``autonomy_loop_log`` row per cycle via ``_log_cycle``
        so the Dev HQ job-monitoring view (#2105 infrastructure) shows
        a timeline.
        """
        try:
            import sys
            from concurrent.futures import ThreadPoolExecutor

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.delegation_service import run_delegation_cycle

            # Lazy-init persistent state, reused across 30s cycles:
            #  _delegate_pool     — bounded executor (concurrency workers)
            #  _delegate_inflight — carry-over futures still running from a
            #                       previous cycle (keeps their slot busy so we
            #                       never oversubmit the pool).
            if not hasattr(self, "_delegate_pool"):
                self._delegate_pool = ThreadPoolExecutor(
                    max_workers=self._DELEGATE_CONCURRENCY,
                    thread_name_prefix="delegate-task",
                )
                self._delegate_inflight = []

            run_delegation_cycle(
                self._delegate_pool,
                self._delegate_inflight,
                concurrency=self._DELEGATE_CONCURRENCY,
                cycle_budget_secs=self._DELEGATE_CYCLE_BUDGET_SECS,
                capability_timeouts=self._DELEGATE_CAPABILITY_TIMEOUTS,
                default_timeout=self._DELEGATE_DEFAULT_TIMEOUT_SECS,
                log_cycle=self._log_cycle,
            )
        except Exception as e:
            logger.error("delegate_task_worker failed: %s", e)
            try:
                self._log_cycle(
                    job_name="delegate_task_worker",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=0,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # K.I.N. Welfare + Budget Digest (Project #272 / Task #2106)
    # ------------------------------------------------------------------

    def _run_triage_consumer(self):
        """A.R.C.H.I.E. triage consumer (Unified Voice Wave 2, #2264).

        Fetches pending director_reports from archie-comms every 30s,
        classifies each one using DB-driven policies + default rules,
        marks it triaged. Only 'escalate'-classified reports reach Telegram
        and are sent as A.R.C.H.I.E. — enforcing the unified voice contract.
        """
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.director_report_service import (
                classify_report,
                get_pending_reports,
                get_policies,
                triage_report,
            )
            from services.telegram_service import send as telegram_send

            reports = get_pending_reports(limit=10)
            if not reports:
                return

            policies = get_policies()
            escalated = 0
            for report in reports:
                action, reason = classify_report(report, policies)
                triage_report(report["id"], action, reason)

                if action == "escalate":
                    try:
                        tg_res = telegram_send(
                            category=report.get("category", "system"),
                            title=f"[{report['severity'].upper()}] {report['title']}",
                            message=(
                                f"From: {report['director_agent']} ({report['department']})\n"
                                f"Summary: {report['summary']}\n"
                                f"Triage: Escalated — {reason}"
                            ),
                            source_agent="A.R.C.H.I.E.",
                            force=True,
                            _privileged=True,
                        )
                        escalated += 1
                        # #4325: persist the Telegram message id on the approval row so an
                        # action taken on the DHQ Approvals tab can echo back onto the
                        # Telegram message (edit + drop buttons). Best-effort, never breaks
                        # the consumer. The approval id is the autonomy_approval_queue.id
                        # embedded in the report title ("... #<id>").
                        if (
                            report.get("category") == "approval_request"
                            and isinstance(tg_res, dict)
                            and tg_res.get("message_id")
                        ):
                            try:
                                import re as _re2

                                _am = _re2.search(r"#(\d+)", report.get("title") or "")
                                if _am:
                                    _aid = int(_am.group(1))
                                    _c = get_db()
                                    try:
                                        _cur = _c.cursor()
                                        _cur.execute(
                                            "UPDATE autonomy_approval_queue "
                                            "SET telegram_message_id = %s WHERE id = %s",
                                            (tg_res.get("message_id"), _aid),
                                        )
                                        _c.commit()
                                    finally:
                                        _c.close()
                            except Exception as _mid_err:
                                logger.warning("triage_consumer: message_id persist failed: %s", _mid_err)
                    except Exception as tg_err:
                        logger.warning("triage_consumer: Telegram send failed: %s", tg_err)

            logger.info(
                "triage_consumer: processed=%d escalated=%d",
                len(reports),
                escalated,
            )
        except Exception as e:
            logger.error("triage_consumer failed: %s", e)

    def _run_ethos_ethics_brief(self):
        """Weekly E.T.H.O.S. ethics brief (task #3277).

        E.T.H.O.S. (agent 336, Legal & Regulatory) is the platform's ethics
        analyst. Once a week it reviews two inputs and drafts an ethics brief:
          1. K.I.N.'s agent-welfare digest — non-exploitative AI is a core
             C.R.E.E.D. mandate, so agent welfare IS an ethics matter. This is
             the E.T.H.O.S.<->K.I.N. collaboration: K.I.N. operates welfare,
             E.T.H.O.S. provides ethics oversight on it.
          2. The week's governance_audit_log (events by category).

        Dispatched to E.T.H.O.S. via the DHQ dispatcher (capability=ethics_review;
        cloud escalation is already globally off via escalation_mode='local_only')
        and persisted as a vault_note (source_type='ethos_ethics_brief'). Fails
        gracefully — always logs the cycle, never raises into the scheduler.
        """
        start = time.time()
        import json as _json
        import os as _os
        import sys as _sys

        _platform_v2 = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "platform_v2",
        )
        _sys.path.insert(0, _platform_v2)

        welfare_summary = {}
        gov_summary = []
        brief_text = None
        persisted = False
        try:
            # Input 1 — K.I.N. welfare digest (the collaboration the owner asked for)
            try:
                from services.agent_service import get_kin_welfare_digest

                digest = get_kin_welfare_digest()
                welfare_summary = digest.get("summary_metrics", {}) or {}
            except Exception as wexc:
                logger.warning("E.T.H.O.S.: K.I.N. welfare digest unavailable: %s", wexc)

            # Input 2 — governance events over the last 7 days, by category
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT event_category, COUNT(*) AS n
                    FROM governance_audit_log
                    WHERE timestamp >= NOW() - INTERVAL '7 days'
                    GROUP BY event_category
                    ORDER BY n DESC
                    LIMIT 20
                    """
                )
                gov_summary = [{"category": r[0], "count": int(r[1])} for r in (cur.fetchall() or [])]
            finally:
                conn.close()

            # Dispatch to E.T.H.O.S. for the ethics assessment
            import tools.department_hq.services.department_dispatcher as _ddd

            prompt = (
                "You are E.T.H.O.S. (Ethical Transparency & Harmonization Oversight "
                "System), the AI ethics analyst for the A.R.C.H.I.E. platform and the "
                "C.R.E.E.D. governance institute.\n\n"
                "Write a concise weekly ETHICS BRIEF from the data below. Cover: "
                "(1) agent welfare ethics — is the platform treating its agents "
                "non-exploitatively? (this welfare data comes from K.I.N., HR & "
                "Culture); (2) governance activity — any ethical concerns in the "
                "week's events; (3) 2-4 concrete recommendations. Map findings to the "
                "five C.R.E.E.D. pillars (accountability, fairness, privacy, safety, "
                "transparency). Be specific and honest; flag risks plainly.\n\n"
                f"AGENT WELFARE (from K.I.N.):\n"
                f"{_json.dumps(welfare_summary, indent=2, default=str)}\n\n"
                f"GOVERNANCE EVENTS (last 7 days, by category):\n"
                f"{_json.dumps(gov_summary, indent=2, default=str)}\n"
            )
            try:
                result = _ddd.dispatch(
                    capability="ethics_review",
                    prompt=prompt,
                    prefer_agent="E.T.H.O.S.",
                    source_product="archie_platform",
                )
                if result is not None and getattr(result, "success", False):
                    brief_text = (getattr(result, "response", "") or "").strip()
            except Exception as dexc:
                logger.warning("E.T.H.O.S.: dispatch failed: %s", dexc)

            # Persist the brief as a vault_note (visible — not agent-quarantined)
            if brief_text:
                from services.time_utils import now_local_str

                conn2 = get_db()
                try:
                    cur2 = conn2.cursor()
                    title = f"E.T.H.O.S. Weekly Ethics Brief — {now_local_str()}"
                    cur2.execute(
                        """
                        INSERT INTO knowledge_base
                          (title, content, knowledge_type, source_type, category,
                           importance_score, created_at)
                        VALUES (%s, %s, 'vault_note', 'ethos_ethics_brief',
                                'governance', 0.85, NOW())
                        """,
                        (title, brief_text),
                    )
                    conn2.commit()
                    persisted = True
                finally:
                    conn2.close()
        except Exception as exc:
            logger.error("E.T.H.O.S. ethics brief failed: %s", exc)

        duration_ms = int((time.time() - start) * 1000)
        self._log_cycle(
            job_name="ethos_ethics_brief",
            items_processed=len(gov_summary),
            items_failed=0 if persisted else 1,
            duration_ms=duration_ms,
            details={
                "welfare_metrics": welfare_summary,
                "gov_categories": gov_summary,
                "brief_persisted": persisted,
                "brief_chars": len(brief_text or ""),
            },
        )

    def _run_creed_grant_deadline_reminder(self):
        """Daily reminder for C.R.E.E.D. grant deadlines within 7 days (task #3612).

        Telegram-alerts the owner about active grants (creed_grants) whose deadline
        falls within the next 7 days, de-duplicated via last_reminder_at (max once
        per 3 days per grant). Dormant until grants have deadlines. Best-effort.
        """
        start = time.time()
        sent = 0
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, funder, title, deadline FROM creed_grants
                    WHERE deadline IS NOT NULL
                      AND deadline >= CURRENT_DATE
                      AND deadline <= CURRENT_DATE + INTERVAL '7 days'
                      AND status NOT IN ('awarded', 'declined')
                      AND (last_reminder_at IS NULL
                           OR last_reminder_at < NOW() - INTERVAL '3 days')
                    ORDER BY deadline ASC
                    """
                )
                rows = cur.fetchall() or []
                if rows:
                    lines = [f"• {r[1]} / {r[2]} — due {r[3]}" for r in rows]
                    msg = "C.R.E.E.D. grant deadlines within 7 days:\n" + "\n".join(lines)
                    try:
                        import sys as _sys

                        _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                        from services import telegram_service

                        telegram_service.send_info("Grant deadlines", msg)
                        sent = len(rows)
                    except Exception as te:
                        logger.warning("grant reminder Telegram failed: %s", te)
                    cur.execute(
                        "UPDATE creed_grants SET last_reminder_at = NOW() WHERE id = ANY(%s)",
                        ([r[0] for r in rows],),
                    )
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error("creed grant deadline reminder failed: %s", e)

        self._log_cycle(
            job_name="creed_grant_deadline_reminder",
            items_processed=sent,
            items_failed=0,
            duration_ms=int((time.time() - start) * 1000),
            details={"reminders_sent": sent},
        )

    def _run_kin_welfare_digest(self):
        """Daily K.I.N. digest — 4-phase welfare intelligence pipeline.

        Phase 1: get_kin_welfare_digest() collects raw data (Python, unchanged).
        Phase 2: K.I.N. LLM assessment via dispatcher (_kin_assess_welfare).
        Phase 3: K.I.N. autonomous actions — recovery/cooldown/barracks/workload_cap.
        Phase 4: C.R.E.E.D. governance filings + A.R.C.H.I.E. severity report.

        Graceful degradation: if K.I.N. dispatch fails, falls back to error-severity
        Telegram (old behaviour) and still logs the cycle.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.agent_service import (
                format_kin_digest_message,
                get_kin_welfare_digest,
            )

            # Phase 1: Data collection
            digest = get_kin_welfare_digest()
            severity = digest["severity"]
            metrics = digest["summary_metrics"]

            # Phase 2: K.I.N. LLM assessment
            assessment = self._kin_assess_welfare(digest)
            duration_ms = int((time.time() - start) * 1000)
            actions_taken = 0
            flags_filed = 0

            if assessment:
                conn = get_db()
                try:
                    # Phase 3: Autonomous actions — validated against the flag that
                    # raised each agent, so the remedy has to match the diagnosis (#5176)
                    _flag_by_agent = {
                        f.get("agent_id"): f.get("flag") for f in digest.get("per_agent_flags", []) if f.get("agent_id")
                    }
                    actions_taken = self._kin_execute_actions(assessment.get("actions", []), conn, _flag_by_agent)
                    # Phase 4a: C.R.E.E.D. ethics filing
                    flags_filed = self._kin_file_creed(assessment.get("creed_flags", []), conn)
                finally:
                    conn.close()

                # Phase 4b: A.R.C.H.I.E. severity report
                try:
                    self._kin_report_to_archie(assessment["archie_report"], actions_taken, flags_filed)
                except Exception as report_err:
                    logger.warning("K.I.N.: A.R.C.H.I.E. report failed: %s", report_err)

            else:
                # K.I.N. unavailable — fallback: send Telegram directly for error severity
                if severity == "error":
                    try:
                        self._send_telegram(format_kin_digest_message(digest))
                    except Exception:
                        pass

            # Always log the cycle
            self._log_cycle(
                job_name="kin_welfare_digest",
                items_processed=metrics["per_agent_flag_count"],
                items_failed=metrics["total_over_budget"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "reasons": digest.get("reasons", []),
                    "department_count": metrics["department_count"],
                    "kin_assessed": assessment is not None,
                    "actions_taken": actions_taken,
                    "creed_flags_filed": flags_filed,
                },
            )

            # Legacy system_notifications for warning/error (keeps dashboard alert working)
            if severity in ("warning", "error"):
                try:
                    body = format_kin_digest_message(digest)
                    conn2 = get_db()
                    cur2 = conn2.cursor()
                    cur2.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"K.I.N. — {severity} in crew welfare / budgets",
                            body,
                            "kin",
                            "high" if severity == "error" else "normal",
                            "🧑‍⚕️",
                            "/tools/department-hq#overview",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn2.commit()
                    cur2.close()
                    conn2.close()
                except Exception as notify_err:
                    logger.warning("K.I.N. digest: system_notifications insert failed: %s", notify_err)

        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle(
                job_name="kin_welfare_digest",
                items_processed=0,
                items_failed=1,
                duration_ms=duration_ms,
                error_message=str(exc)[:200],
            )
            logger.exception("K.I.N. welfare digest failed")

    def _kin_assess_welfare(self, digest: dict):
        """Phase 2: Dispatch to K.I.N. for LLM welfare assessment. Returns parsed dict or None."""
        import json as _json
        import os as _os
        import sys as _sys

        _platform_v2 = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "platform_v2")
        _sys.path.insert(0, _platform_v2)
        import tools.department_hq.services.department_dispatcher as _ddd

        metrics = digest.get("summary_metrics", {})
        flags = digest.get("per_agent_flags", [])[:20]  # cap prompt size

        prompt = (
            "You are K.I.N. (Kinship & Internal Nurturing), Director of Human Resources & Culture "
            "on the A.R.C.H.I.E. platform.\n"
            f"Today's welfare snapshot:\n{_json.dumps({'metrics': metrics, 'agent_flags': flags}, indent=2)}\n\n"
            "Assess the platform's welfare state. Return ONLY valid JSON with this exact schema "
            "(no markdown, no explanation):\n"
            '{"summary":"<2-3 sentences>","at_risk_agents":[{"agent_id":0,"name":"","reason":"","severity":"low"}],'
            '"idle_neglected":[{"agent_id":0,"name":"","days_idle":0,"department":""}],'
            '"actions":[{"type":"welfare_recovery","agent_id":0,"reason":"","value":null}],'
            '"creed_flags":[{"event_type":"","agent_id":0,"reason":"","severity":"low"}],'
            '"archie_report":{"message":"","severity":"info"}}'
        )

        try:
            result = _ddd.dispatch(
                capability="welfare",
                prompt=prompt,
                prefer_agent="K.I.N.",
                source_product="archie_platform",
            )
        except Exception as exc:
            logger.warning("K.I.N. welfare: dispatch failed: %s", exc)
            return None

        if not result or getattr(result, "queued", False) or not result.success:
            return None

        try:
            import re as _re

            text = (result.response or "").strip()
            text = _re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            return _json.loads(text.strip())
        except Exception:
            logger.warning("K.I.N. welfare: failed to parse JSON from K.I.N. response")
            return None

    def _kin_execute_actions(self, actions: list, conn, flag_by_agent: dict = None) -> int:
        """Phase 3: Execute K.I.N.'s autonomous welfare decisions. Returns count of applied actions.

        ``flag_by_agent`` maps agent_id -> the welfare flag that raised it (from the
        digest's ``per_agent_flags``). Actions are validated against that flag before
        execution (#5176): K.I.N. is a 7B model returning free-form JSON, so a prompt
        instruction cannot enforce that the remedy matches the diagnosis. Refused
        actions are audited as ``skipped``, never silently dropped.
        """
        import sys as _sys
        import os as _os
        import psycopg2.extras as _extras
        from datetime import date as _date

        _platform_v2 = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "platform_v2")
        _sys.path.insert(0, _platform_v2)
        from services.agent_service import transition_shift_state
        from services.welfare_load import kin_action_allowed
        from database import get_db_cursor

        applied = 0
        for action in actions:
            action_type = action.get("type")
            agent_id = action.get("agent_id")
            reason = action.get("reason", "K.I.N. welfare assessment")
            if not action_type or not agent_id:
                try:
                    cur = conn.cursor()
                    try:
                        cur.execute(
                            """INSERT INTO governance_audit_log
                               (event_type, event_category, agent_id, action, reason, outcome, details)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (
                                "kin_welfare_action",
                                "welfare_ethics",
                                agent_id,
                                action_type or "unknown",
                                reason,
                                "skipped",
                                _extras.Json(
                                    {
                                        "filed_by": "K.I.N.",
                                        "digest_date": str(_date.today()),
                                        "skip_reason": "missing agent_id or action_type",
                                    }
                                ),
                            ),
                        )
                        conn.commit()
                    finally:
                        cur.close()
                except Exception:
                    pass
                continue

            # Refuse a remedy that contradicts the diagnosis (#5176). recover_idle()
            # WRITES stress -0.15 / energy +0.2, so applying it to an over_budget agent
            # suppresses the overload signal that raised the flag.
            _flag = (flag_by_agent or {}).get(agent_id)
            if not kin_action_allowed(_flag, action_type):
                try:
                    cur = conn.cursor()
                    try:
                        cur.execute(
                            """INSERT INTO governance_audit_log
                               (event_type, event_category, agent_id, action, reason, outcome, details)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (
                                "kin_welfare_action",
                                "welfare_ethics",
                                agent_id,
                                action_type,
                                reason,
                                "skipped",
                                _extras.Json(
                                    {
                                        "filed_by": "K.I.N.",
                                        "digest_date": str(_date.today()),
                                        "welfare_flag": _flag,
                                        "skip_reason": (
                                            f"action '{action_type}' is not a permitted " f"response to flag '{_flag}'"
                                        ),
                                    }
                                ),
                            ),
                        )
                        conn.commit()
                    finally:
                        cur.close()
                except Exception:
                    pass
                logger.info(
                    "K.I.N.: refused %s on agent %s (flag=%s) — remedy does not match diagnosis",
                    action_type,
                    agent_id,
                    _flag,
                )
                continue

            outcome = "applied"
            try:
                if action_type == "welfare_recovery":
                    recover_idle(agent_id)
                elif action_type == "cooldown":
                    transition_shift_state(agent_id, "cooldown", "kin_welfare_action")
                elif action_type == "barracks":
                    transition_shift_state(agent_id, "barracked", "kin_welfare_action")
                elif action_type == "workload_cap":
                    cap = int(action.get("value") or 25)
                    with get_db_cursor(commit=True) as (_, cur):
                        cur.execute(
                            "UPDATE agent_budgets SET task_queue_limit = %s WHERE agent_id = %s",
                            (cap, agent_id),
                        )
                        if cur.rowcount == 0:
                            raise ValueError(f"No agent_budgets row for agent_id={agent_id}")
                else:
                    continue
                applied += 1
            except Exception as exc:
                logger.warning("K.I.N. action %s on agent %s failed: %s", action_type, agent_id, exc)
                outcome = "failed"

            try:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """INSERT INTO governance_audit_log
                           (event_type, event_category, agent_id, action, reason, outcome, details)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            "kin_welfare_action",
                            "welfare_ethics",
                            agent_id,
                            action_type,
                            reason,
                            outcome,
                            _extras.Json({"filed_by": "K.I.N.", "digest_date": str(_date.today())}),
                        ),
                    )
                    conn.commit()
                finally:
                    cur.close()
            except Exception as log_exc:
                logger.warning("K.I.N.: governance log failed for action %s: %s", action_type, log_exc)

        return applied

    def _kin_file_creed(self, creed_flags: list, conn) -> int:
        """Phase 4a: File K.I.N.'s ethics concerns to C.R.E.E.D. governance_audit_log.
        Returns count of filed entries. Non-fatal — logs warnings on failure."""
        import psycopg2.extras as _extras
        from datetime import date as _date

        filed = 0
        for flag in creed_flags:
            try:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """INSERT INTO governance_audit_log
                           (event_type, event_category, agent_id, action, reason, outcome, details)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            flag.get("event_type", "ethics_concern"),
                            "welfare_ethics",
                            flag.get("agent_id"),
                            "ethics_concern",
                            flag.get("reason", ""),
                            "flagged",
                            _extras.Json(
                                {
                                    "severity": flag.get("severity", "low"),
                                    "filed_by": "K.I.N.",
                                    "digest_date": str(_date.today()),
                                }
                            ),
                        ),
                    )
                    conn.commit()
                    filed += 1
                finally:
                    cur.close()
            except Exception as exc:
                logger.warning("K.I.N.: C.R.E.E.D. filing failed for %s: %s", flag.get("event_type"), exc)
        return filed

    def _kin_report_to_archie(self, archie_report: dict, actions_taken: int, flags_filed: int):
        """Phase 4b: Route K.I.N.'s welfare report through A.R.C.H.I.E. with severity-based escalation.

        K.I.N. reports UP to A.R.C.H.I.E. — never directly to Telegram.
        A.R.C.H.I.E. controls the outbound voice based on severity.
          critical/alert → send (category="alert") → immediate Telegram push
          warning        → send (category="info")  → included in digest
          info           → internal log only, no Telegram
        """
        import sys as _sys
        import os as _os

        _platform_v2 = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "platform_v2")
        _sys.path.insert(0, _platform_v2)
        from services.director_report_service import submit_via_inbox as _kin_digest_inbox

        severity = archie_report.get("severity", "info")
        message = archie_report.get("message", "K.I.N. welfare assessment complete.")
        if actions_taken or flags_filed:
            message += f"\n\n✅ Actions taken: {actions_taken} | C.R.E.E.D. filings: {flags_filed}"

        # K.I.N. routes through A.R.C.H.I.E.'s inbox — A.R.C.H.I.E. is the sole Telegram voice.
        # Inbox entry shows in Approvals tab + A.R.C.H.I.E. relays to Telegram when warranted.
        if severity in ("critical", "alert"):
            _kin_digest_inbox(
                category="welfare",
                title="🚨 K.I.N. Welfare Alert",
                message=message,
                source_agent="K.I.N.",
                severity="critical",
                department="Human Resources & Culture",
            )
        elif severity == "warning":
            _kin_digest_inbox(
                category="welfare",
                title="😴 K.I.N. Welfare Digest",
                message=message,
                source_agent="K.I.N.",
                severity="medium",
                department="Human Resources & Culture",
                cooldown_hours=4.0,
            )
        # severity == "info" → no notification; A.R.C.H.I.E. stays quiet on healthy days

        logger.info(
            "K.I.N. welfare report sent: severity=%s actions=%d creed=%d",
            severity,
            actions_taken,
            flags_filed,
        )

    # ------------------------------------------------------------------
    # F.O.R.G.E. Dependency Drift Audit (Project #272 Phase 2 / Task #2109)
    # ------------------------------------------------------------------

    def _run_pr_review_poll(self):
        """Poll GitHub for open PRs across all tracked repos (Project #247)."""
        try:
            from tools.repair_bay.services.pr_review_service import (
                poll_open_prs,
                sync_closed_prs,
                get_tracked_repos,
            )

            for repo in get_tracked_repos():
                result = poll_open_prs(repo=repo)
                closed = sync_closed_prs(repo=repo)
                logger.info(
                    "pr_review_poll [%s]: polled=%d inserted=%d updated=%d closed_synced=%d",
                    repo,
                    result.get("polled"),
                    result.get("inserted"),
                    result.get("updated"),
                    closed,
                )
        except Exception as e:
            logger.error("pr_review_poll failed: %s", e)

    def _run_pr_diff_analysis(self):
        """Phase 2: F.O.R.G.E. AI code review of pending PRs (Project #247, Task #1800)."""
        try:
            from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

            result = analyze_pending_prs(max_prs=3)
            logger.info(
                "pr_diff_analysis: processed=%d failed=%d skipped=%d",
                result.get("processed"),
                result.get("failed"),
                result.get("skipped"),
            )
        except Exception as e:
            logger.error("pr_diff_analysis failed: %s", e)

    def _run_review_reaper(self):
        """#4583: recover PR reviews stuck 'in_progress' past the stale window, then re-drive them.

        Makes F.O.R.G.E. review durable — a review whose on-demand review_pr() died with its CLI
        no longer stays stuck forever; the sidecar resets it (or 'skipped' past the retry cap) and
        re-runs it server-side. Runs in the archie_scheduler sidecar, never the web thread.
        """
        try:
            from tools.repair_bay.services.pr_review_service import reap_stale_reviews

            res = reap_stale_reviews()
            reset = res.get("reset", [])
            skipped = res.get("skipped", [])
            if reset or skipped:
                logger.info("review_reaper: reset=%d skipped=%d", len(reset), len(skipped))
            # Re-drive promptly via the established drain (same path + auto-merge policy as the
            # 10-min forge_pr_diff_analysis poller), instead of waiting for its next tick. No-op
            # if nothing was reset. A rare double-drive overlap with that poller is harmless.
            if reset:
                from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

                analyze_pending_prs(max_prs=max(3, len(reset)))
        except Exception as e:
            logger.error("review_reaper failed: %s", e)

    def _run_repo_health_check(self):
        """Daily per-repo GitHub presence health check (Project #247, Task #1803)."""
        try:
            from tools.repair_bay.services.repo_health_service import run_health_checks

            result = run_health_checks()
            self._log_autonomy_action(
                action_type="repo_health_check",
                details={
                    "checked": result.get("checked", 0),
                    "healthy": result.get("healthy", 0),
                    "unhealthy": result.get("unhealthy", 0),
                },
                success=True,
            )
            logger.info(
                "repo_health_check: checked=%d healthy=%d unhealthy=%d",
                result.get("checked"),
                result.get("healthy"),
                result.get("unhealthy"),
            )
        except Exception as e:
            logger.error("repo_health_check failed: %s", e)
            self._log_autonomy_action(
                action_type="repo_health_check",
                details={"error": str(e)},
                success=False,
            )

    def _run_briefing_health(self):
        """Daily P.R.O.B.E. check — runs every agent chat briefing and flags any
        returning a swallowed error (schema drift) instead of live module state.

        Delegates to ``services.briefing_health_service.check_briefing_health``
        (single source of truth). Surfaces via autonomy_loop_log (always) and a
        warning log on failure; items_failed > 0 also makes it appear in the
        session_briefing anomalies feed on next boot. See mistake_learned #269358.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.briefing_health_service import (
                check_briefing_health,
                format_alert_message,
            )

            result = check_briefing_health()
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="probe_briefing_health",
                items_processed=result["total"],
                items_failed=result["anomaly_count"],
                duration_ms=duration_ms,
                details={
                    "severity": result["severity"],
                    "summary_metrics": result["summary_metrics"],
                    "reasons": result["reasons"],
                },
            )

            if result["severity"] in ("warning", "error"):
                logger.warning("[ProbeBriefingHealth] %s", format_alert_message(result))
        except Exception as e:
            logger.error("[ProbeBriefingHealth] check failed: %s", e)

    def _run_dep_drift_audit(self):
        """Daily drift audit — requirements.txt vs running container pip freeze.

        Delegates to ``services.dep_drift_service.check_dep_drift`` (single
        source of truth). Surfaces via autonomy_loop_log (always),
        system_notifications (severity >= warning), Telegram (error).

        The MCP tool ``mcp__archie__check_dep_drift`` composes onto the
        same service function for on-demand invocation.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.dep_drift_service import (
                check_dep_drift,
                format_alert_message,
            )

            result = check_dep_drift()
            severity = result["severity"]
            metrics = result["summary_metrics"]
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="forge_dep_drift",
                items_processed=result["anomaly_count"],
                items_failed=metrics["missing"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "reasons": result.get("reasons", []),
                    "requirements_count": result["requirements_count"],
                    "installed_count": result["installed_count"],
                },
            )

            if severity in ("warning", "error"):
                body = format_alert_message(result)
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"F.O.R.G.E. — {severity} in dependency drift",
                            body,
                            "forge",
                            "high" if severity == "error" else "normal",
                            "⚙️",
                            "/tools/repair-bay",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as notify_err:
                    logger.warning(
                        "F.O.R.G.E. dep drift: system_notifications insert failed: %s",
                        notify_err,
                    )

            if severity == "error":
                try:
                    self._send_telegram(format_alert_message(result))
                except Exception as tg_err:
                    logger.warning("F.O.R.G.E. dep drift: Telegram dispatch failed: %s", tg_err)

            logger.info(
                "F.O.R.G.E. dep drift: severity=%s anomalies=%d in %dms",
                severity,
                result["anomaly_count"],
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("F.O.R.G.E. dep drift audit failed: %s", e)
            try:
                self._log_cycle(
                    job_name="forge_dep_drift",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Fleet Capacity Report (#2516 / ADR-555)
    # ------------------------------------------------------------------

    def _run_fleet_capacity_report(self):
        """Daily fleet utilisation digest — flag nodes that need upgrades.

        Reads `remote_nodes` directly (no dispatch). Computes per-node load %
        and consecutive-day high-utilisation streaks via prior vault notes.
        Stores a vault_note summarising state and pings A.R.C.H.I.E. via
        `telegram_service.send_info` if any node sustains >=80% load for
        7 consecutive days.

        Pure observability — does NOT modify routing, agents, or fleet
        state. Phase 1 of #2516.
        """
        from datetime import datetime

        try:
            from database import get_db_cursor
            from services.fleet_resource_router import is_stale, utilization_pct
        except Exception as e:
            logger.warning(f"fleet_capacity_report: imports unavailable, skipping ({e})")
            return

        nodes_summary = []
        high_util_nodes = []
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT node_id, node_name, status, last_heartbeat,
                           gpu_available, gpu_vram_gb, ram_gb, cpu_cores,
                           current_load, max_concurrent,
                           total_requests, failed_requests, priority
                      FROM remote_nodes
                     WHERE is_active = TRUE
                  ORDER BY priority DESC, node_name
                    """
                )
                for row in cur.fetchall():
                    node = dict(row)
                    pct = utilization_pct(node)
                    stale = is_stale(node)
                    nodes_summary.append(
                        {
                            "node_id": node["node_id"],
                            "node_name": node["node_name"],
                            "status": node["status"],
                            "load_pct": pct,
                            "stale": stale,
                            "gpu_available": bool(node.get("gpu_available")),
                            "gpu_vram_gb": node.get("gpu_vram_gb"),
                            "ram_gb": node.get("ram_gb"),
                        }
                    )
                    if pct >= 80 and not stale:
                        high_util_nodes.append((node["node_name"], pct))
        except Exception as e:
            logger.error(f"fleet_capacity_report: DB read failed: {e}")
            try:
                self._log_cycle(
                    "fleet_capacity_report",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=0,
                    error_message=str(e),
                )
            except Exception:
                pass
            return

        # Persist a vault note for trend analysis (next run can correlate).
        try:
            from tools.consciousness.services.knowledge_service import create_doc

            content_lines = [
                f"# Fleet Capacity Report — {now_local_str()}",
                "",
                f"Active nodes: {len(nodes_summary)}",
                f"High-utilisation (>=80%) nodes: {len(high_util_nodes)}",
                "",
                "## Per-node summary",
            ]
            for n in nodes_summary:
                marker = "⚠️ " if n["load_pct"] >= 80 and not n["stale"] else ""
                stale_tag = " [stale]" if n["stale"] else ""
                content_lines.append(
                    f"- {marker}{n['node_name']} ({n['node_id']}){stale_tag} — "
                    f"{n['load_pct']}% load, "
                    f"{'GPU ' + str(n['gpu_vram_gb']) + 'GB' if n['gpu_available'] else 'CPU'}, "
                    f"{n['ram_gb']}GB RAM, status={n['status']}"
                )
            content_lines.append("")
            content_lines.append("Tags: fleet, capacity-report, autonomy")
            create_doc(
                title=f"Fleet Capacity Report {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                content="\n".join(content_lines),
                doc_type="user",
                category="fleet_capacity",
            )
        except Exception as e:
            logger.warning(f"fleet_capacity_report: KB write failed: {e}")

        # A.R.C.H.I.E.-voice Telegram alert if any node is sustained-hot.
        if high_util_nodes:
            try:
                from services.telegram_service import send_info

                msg = "Fleet capacity heads-up — sustained high load:\n" + "\n".join(
                    f"  • {n} at {pct}%" for n, pct in high_util_nodes
                )
                send_info(msg, source_agent="A.R.C.H.I.E.")
            except Exception as e:
                logger.warning(f"fleet_capacity_report: telegram send failed: {e}")

        try:
            self._log_cycle(
                "fleet_capacity_report",
                items_processed=len(nodes_summary),
                items_failed=0,
                duration_ms=0,
                details={
                    "high_util_nodes": [n for n, _ in high_util_nodes],
                    "total_active": len(nodes_summary),
                },
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # F.O.R.G.E. GitHub Presence Audit (Project #247 / Task #1803)
    # ------------------------------------------------------------------

    def _run_github_presence_audit(self):
        """Weekly F.O.R.G.E. audit of KytranKatarn GitHub public presence (Project #247, Task #1803)."""
        try:
            from tools.repair_bay.services.github_presence_service import run_presence_audit

            result = run_presence_audit()
            self._log_autonomy_action(
                action_type="github_presence_audit",
                details={
                    "repo_count": result.get("repo_count", 0),
                    "success": result.get("success", False),
                },
                success=True,
            )
            logger.info(
                "github_presence_audit: repos=%d success=%s",
                result.get("repo_count"),
                result.get("success"),
            )
        except Exception as e:
            logger.error("github_presence_audit failed: %s", e)
            self._log_autonomy_action(
                action_type="github_presence_audit",
                details={"error": str(e)},
                success=False,
            )

    # ------------------------------------------------------------------
    # Tiered PR Merge Authority (Project #244 / feat/tiered-pr-merge-authority)
    # ------------------------------------------------------------------

    def _request_kytran_pr_approval(self, pr_number: int, title: str, summary: str, reason: str = None) -> None:
        """Send a Telegram message with approve/deny buttons to Kytran.

        ``reason`` explains WHY he is being asked. It defaults to the Tier 3
        wording so existing callers are unchanged; a merge the automation was
        REFUSED from completing (#5413) passes the gate's own refusal text, so
        the message says what is actually blocking rather than implying the PR
        was classified Tier 3.
        """
        from services.telegram_service import send_with_buttons  # noqa: PLC0415

        short_summary = summary[:400] if summary else "No review summary available."
        send_with_buttons(
            category="system",
            title=f"PR #{pr_number} — Merge Approval Required",
            message=(
                f"*PR #{pr_number}:* {title}\n\n"
                f"*F.O.R.G.E. Review:*\n{short_summary}\n\n"
                f"{reason or 'Tier 3 — requires your approval before merge.'}"
            ),
            buttons=[
                {"text": "✅ Merge", "callback_data": f"pr_merge_approve_{pr_number}"},
                {"text": "❌ Deny", "callback_data": f"pr_merge_deny_{pr_number}"},
            ],
            source_agent="A.R.C.H.I.E.",
        )

    def _escalate_blocked_merge(self, review, result, tier: int) -> bool:
        """Hand a merge the automation CANNOT complete up to Kytran — exactly once.

        #5413. A Tier-1/Tier-2 merge REFUSAL used to be a ``logger.warning`` and
        nothing else: no Telegram, no state. Because neither guard field was
        written, the worker re-attempted a merge that could never succeed on
        every 2-minute tick, forever — while the human who has to act was never
        told. The escalation chain terminated in a log line (PR #2551 sat that
        way; PR #2547 before it).

        ONLY A GOVERNANCE REFUSAL ESCALATES. ``governance_blocked`` is set by
        ``merge_pr``'s gate, which runs BEFORE any GitHub call — it means a rule
        said no, so re-attempting in two minutes cannot change the answer and a
        human decision is genuinely required. Everything else (GitHub 5xx, merge
        conflict, CI still pending) leaves the flag unset and keeps today's
        retry, which is correct for something that may clear on its own. That
        line needs no string matching against error text, which would rot the
        moment a message is reworded.

        Ordering mirrors the Tier 3 branch (#5283): the durable Approvals-tab
        row is opened FIRST and independently of the Telegram send, so an
        undelivered or dismissed message still leaves the owner something to act
        on. ``_mark_kytran_approval_sent`` is last — it is also what makes the
        worker's own guard skip this PR next tick, ending the retry loop.

        Returns True when the PR was escalated.
        """
        from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
            _mark_kytran_approval_sent,
            _mark_tier_processed,
            open_pr_merge_approval,
        )
        from tools.repair_bay.services.github_service import pr_is_open  # noqa: PLC0415

        if not result.get("governance_blocked"):
            return False

        pr_num = review["pr_number"]
        title = review.get("title") or f"PR #{pr_num}"
        summary = review.get("ai_summary") or ""
        why = result.get("error") or "the merge was refused by the governance gate"

        # #5419. `pr_reviews.state` is refreshed by sync_closed_prs only every 4
        # HOURS, so a PR merged out-of-band still reads 'open' to this worker for
        # hours. The gate is checked BEFORE any GitHub call (deliberately — a
        # refusal must cost no quota), so it never discovers the PR is already
        # merged. And an allowlist-refused PR can ONLY be merged by hand, so
        # EVERY one of them opens this window: the escalation's own success
        # condition guarantees its false positive. Observed on PR #2552, which
        # paged the owner about a merge that had already happened.
        #
        # ASYMMETRIC ON PURPOSE: only a definite False suppresses the notice.
        # `None` (API error, rate limit) still notifies — failing to speak up
        # about a genuinely blocked PR reintroduces the silence #5413 fixed,
        # whereas a redundant ping is just noise.
        if pr_is_open(pr_num, repo=review.get("repo")) is False:
            logger.info(
                "[PRTiers] PR #%s was refused but is already closed/merged — " "marking processed, not paging Kytran",
                pr_num,
            )
            _mark_tier_processed(pr_num, tier=tier)
            return True

        logger.warning(
            "[PRTiers] Tier %s merge REFUSED for PR #%s — escalating to Kytran: %s",
            tier,
            pr_num,
            why,
        )
        approval_id = open_pr_merge_approval(pr_num, title, summary, repo=review.get("repo"))
        self._request_kytran_pr_approval(
            pr_num,
            title,
            summary,
            reason=(
                f"⛔ Tier {tier} auto-merge was REFUSED — a human must merge this " f"deliberately.\n\n*Reason:* {why}"
            ),
        )
        # #5829: mark "asked" only when a QUEUE ROW EXISTS. This flag is checked at
        # the top of the worker loop and permanently suppresses re-escalation, so
        # setting it on a failed/deduped/draft-guarded creation retires the PR from
        # the queue forever while it is still open and unmerged. Telegram alone is
        # not enough — a message scrolls away, a row does not, and the Approvals tab
        # is where the owner actually looks. Same shape as ADR-014: record the
        # artifact, never the intent.
        if approval_id:
            _mark_kytran_approval_sent(pr_num)
            return True
        logger.warning(
            "[PRTiers] PR #%s: no approval row was created (draft guard, dedup or error) — "
            "NOT marking as asked, so the next cycle retries instead of losing it",
            pr_num,
        )
        return False

    def _run_archie_pr_review_worker(self):
        """Job: Tiered PR merge authority — F.O.R.G.E./A.R.C.H.I.E./Kytran governance."""
        import time as _time  # noqa: PLC0415

        start = _time.time()
        try:
            from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
                list_reviews,
                classify_pr_tier,
                verdict_is_approved,
                _mark_tier_processed,
                _mark_kytran_approval_sent,
                open_pr_merge_approval,
            )
            from tools.repair_bay.services.github_service import merge_pr  # noqa: PLC0415
            from services.director_report_service import submit_via_inbox as _forge_inbox  # noqa: PLC0415
            from services.telegram_service import send_info  # noqa: PLC0415

            reviews = list_reviews(state="open", review_status="reviewed")
            processed = 0

            for review in reviews:
                meta = review.get("metadata") or {}
                if meta.get("tier_processed") or meta.get("kytran_approval_sent"):
                    continue

                pr_num = review["pr_number"]
                title = review.get("title") or f"PR #{pr_num}"
                summary = review.get("ai_summary") or ""

                # #5194: review_status='reviewed' only means a review FINISHED — it does
                # NOT mean F.O.R.G.E. approved. This loop used `summary` purely for
                # notification text and never checked the verdict, so PR #2458 was merged
                # on a needs_changes verdict (2026-07-25); it was blocked twice
                # beforehand only by an accidental HTTP 405 "still a draft".
                # github_service.merge_pr now refuses these at the choke point, but skip
                # them here too so the worker stops re-attempting every cycle.
                if not verdict_is_approved(summary):
                    logger.info(
                        "[PRTiers] PR #%s reviewed but NOT approved — skipping (no merge attempt)",
                        pr_num,
                    )
                    continue

                # A DRAFT cannot be merged — GitHub answers HTTP 405 "Pull Request
                # is still a draft" — and nothing marks the attempt processed on
                # failure (correctly: it must still merge once undrafted). So the
                # worker retried forever: 35 attempts in 6 hours for PR #2444
                # alone, and worse since the tick moved 10min -> 2min. That burns
                # GitHub quota and emits a WARNING every cycle, which is how a log
                # line stops being read (#5362).
                #
                # `draft` is recorded by poll_open_prs from the PR-list response,
                # which already carries it — so this check costs ZERO extra API
                # calls. Asking GitHub per tick would re-spend the quota this is
                # meant to save. Absent/unknown (pre-existing rows, or a repo whose
                # poll predates this) reads falsy => NOT skipped, so the worst case
                # is today's behaviour, never a PR silently stuck unmerged.
                if (review.get("metadata") or {}).get("draft"):
                    logger.debug(
                        "[PRTiers] PR #%s is a draft — skipping until it is marked ready",
                        pr_num,
                    )
                    continue

                tier = classify_pr_tier(review)

                if tier == 1:
                    result = merge_pr(pr_num, "squash")
                    if result.get("merged"):
                        _mark_tier_processed(pr_num, tier=1)
                        _forge_inbox(
                            category="pr_reviewed",
                            title=f"F.O.R.G.E. auto-merged PR #{pr_num}",
                            message=f"*{title}*\nTier 1 auto-merge (small, approved).",
                            source_agent="F.O.R.G.E.",
                            severity="info",
                            department="Engineering & Technology",
                        )
                        processed += 1
                    elif self._escalate_blocked_merge(review, result, tier=1):
                        processed += 1
                    else:
                        logger.warning(
                            "[PRTiers] Tier 1 merge failed for PR #%s: %s",
                            pr_num,
                            result.get("error"),
                        )

                elif tier == 2:
                    # Tier 2 is A.R.C.H.I.E. exercising COO authority — declare it so the
                    # governance gate applies HER ceiling (ARCHIE_COO_AUTO_MERGE_MAX_TIER)
                    # and not F.O.R.G.E.'s. Passing no authority here silently clamped the
                    # COO out of her own loop.
                    result = merge_pr(pr_num, "squash", authority="coo")
                    if result.get("merged"):
                        _mark_tier_processed(pr_num, tier=2)
                        send_info(
                            title=f"A.R.C.H.I.E. merged PR #{pr_num}",
                            message=(
                                f"*{title}*\n"
                                f"Tier 2 autonomous merge (COO authority).\n"
                                f"F.O.R.G.E.: {summary[:200]}"
                            ),
                            source_agent="A.R.C.H.I.E.",
                        )
                        processed += 1
                    elif self._escalate_blocked_merge(review, result, tier=2):
                        processed += 1
                    else:
                        logger.warning(
                            "[PRTiers] Tier 2 merge failed for PR #%s: %s",
                            pr_num,
                            result.get("error"),
                        )

                elif tier == 3:
                    # DUAL SURFACE (#5283). The durable Approvals-tab row is opened
                    # FIRST and independently of the Telegram send: Telegram was the
                    # only channel and is send-once, so a missed / dismissed /
                    # undelivered message stranded the PR with nothing pending
                    # anywhere. Opening the row first means a Telegram failure still
                    # leaves the owner something to act on.
                    open_pr_merge_approval(pr_num, title, summary, repo=review.get("repo"))
                    self._request_kytran_pr_approval(pr_num, title, summary)
                    _mark_kytran_approval_sent(pr_num)
                    processed += 1

            elapsed = int((_time.time() - start) * 1000)
            self._log_cycle(
                "archie_pr_review",
                processed,
                0,
                elapsed,
            )

        except Exception as e:
            elapsed = int((_time.time() - start) * 1000)
            logger.warning("[PRTiers] archie_pr_review_worker failed: %s", e)
            self._log_cycle(
                "archie_pr_review",
                0,
                1,
                elapsed,
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # Codex Auto-Queue (Phase B — Job #77)
    # ------------------------------------------------------------------

    def _codex_auto_queue(self):
        """Scan pending tasks in Codex-scoped projects and delegate one per run.

        Reads ``codex_auto_queue_project_ids`` (comma-separated project IDs)
        and ``codex_auto_queue_enabled`` from ``platform_settings``.  Picks the
        highest-priority pending task that has NOT already been deferred to
        Codex and calls ``delegate_task(capability='codex_task', ...)``.  The
        host poller (``scripts/agents/codex-delegation-worker.py``, cron every
        1 min) then claims the deferred row and runs the sandboxed runner.

        One task per job fire — keeps the queue predictable and Codex from
        building up a backlog faster than it can drain.
        """

        from database import get_db_cursor
        from services.delegation_service import delegate_task

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT key, value FROM platform_settings "
                    "WHERE key IN ('codex_auto_queue_enabled', 'codex_auto_queue_project_ids')"
                )
                rows = cur.fetchall()
            settings = {r["key"]: r["value"] for r in (rows or [])}
            if settings.get("codex_auto_queue_enabled", "false").lower() != "true":
                logger.debug("codex_auto_queue: disabled via platform_settings — skipping")
                return

            raw_ids = settings.get("codex_auto_queue_project_ids", "")
            project_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
            if not project_ids:
                logger.warning("codex_auto_queue: no project IDs configured — skipping")
                return

            # ── K.I.N. load gates — queue-time pacing for an EXTERNAL worker.
            # Codex burns the owner's ChatGPT-plan quota, so the cap is budget
            # protection, not ceremony. Gates mirror the platform welfare
            # model: capacity (agent_budgets), drain (queue depth), human
            # attention (pending promote approvals), WP-007 failure standby.
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT ab.task_queue_limit FROM agent_budgets ab "
                    "JOIN agents a ON a.id = ab.agent_id WHERE a.name = 'Codex'"
                )
                row = cur.fetchone()
                daily_cap = int(row["task_queue_limit"]) if row and row.get("task_queue_limit") else 8
                cur.execute(
                    "SELECT COUNT(*) AS n FROM task_execution_log "
                    "WHERE agent_name = 'Codex (CLI)' AND created_at > NOW() - INTERVAL '24 hours'"
                )
                runs_24h = int(cur.fetchone()["n"])
                cur.execute(
                    "SELECT COUNT(*) AS n FROM unified_tasks "
                    "WHERE delegation_args->>'capability' = 'codex_task' "
                    "  AND status NOT IN ('completed', 'blocked', 'cancelled')"
                )
                queue_depth = int(cur.fetchone()["n"])
                cur.execute(
                    "SELECT COUNT(*) AS n FROM autonomy_approval_queue "
                    "WHERE action_type = 'codex_promote' AND status = 'pending'"
                )
                pending_promotes = int(cur.fetchone()["n"])
                cur.execute(
                    "SELECT success, created_at FROM task_execution_log "
                    "WHERE agent_name = 'Codex (CLI)' ORDER BY created_at DESC LIMIT 3"
                )
                recent = cur.fetchall() or []

            if runs_24h >= daily_cap:
                logger.info(
                    "codex_auto_queue: K.I.N. gate — daily cap reached (%s/%s runs in 24h)",
                    runs_24h,
                    daily_cap,
                )
                return
            if queue_depth >= 2:
                logger.info(
                    "codex_auto_queue: K.I.N. gate — %s codex tasks already in flight, letting Codex drain",
                    queue_depth,
                )
                return
            if pending_promotes >= 3:
                logger.info(
                    "codex_auto_queue: K.I.N. gate — %s codex PRs awaiting owner review, not queuing more",
                    pending_promotes,
                )
                return
            if len(recent) == 3 and not any(bool(r["success"]) for r in recent):
                logger.warning(
                    "codex_auto_queue: K.I.N. FAILURE STANDBY — last 3 Codex runs failed; "
                    "auto-queue paused until a run succeeds (WP-007)"
                )
                # Alert once, right after the third failure lands — not every fire.
                from datetime import datetime, timedelta, timezone as _tz

                newest = recent[0]["created_at"]
                if newest and newest > datetime.now(_tz.utc) - timedelta(minutes=35):
                    try:
                        from services import telegram_service

                        telegram_service.send_system(
                            "Codex failure standby (K.I.N.)",
                            "Last 3 Codex runs failed — auto-queue paused until a run "
                            "succeeds. Check /tmp/codex-delegation-worker.log.",
                        )
                    except Exception as _e:
                        logger.warning("codex_auto_queue: standby alert failed: %s", _e)
                return

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT ut.id, ut.title, ut.description, ut.project_id,
                           up.name AS project_name
                    FROM unified_tasks ut
                    LEFT JOIN unified_projects up ON up.id = ut.project_id
                    WHERE ut.project_id = ANY(%s)
                      AND ut.status = 'pending'
                      AND (ut.delegation_args IS NULL
                           -- COALESCE so an empty-object '{}' delegation_args (capability
                           -- absent) is still eligible: without it, ->>'capability' is NULL
                           -- and `NULL != 'codex_task'` is NULL, silently excluding the row.
                           OR (COALESCE(ut.delegation_args->>'capability', '') != 'codex_task'
                               AND NOT ut.delegation_args ? 'codex_queued_delegate_id'))
                    ORDER BY ut.priority DESC, ut.created_at ASC
                    LIMIT 1
                    """,
                    (project_ids,),
                )
                task = cur.fetchone()

            if not task:
                logger.info("codex_auto_queue: no pending tasks in projects %s — nothing to queue", project_ids)
                return

            reason = task["description"] or task["title"] or "No description provided"
            result = delegate_task(
                capability="codex_task",
                reason=reason,
                delegation_source="automation",
                requested_by="codex_auto_queue",
                project_id=task["project_id"],
                priority=task.get("priority") or 5,
            )
            if result.get("success"):
                # Mark the SOURCE task so the next fire can't re-pick it —
                # unmarked sources stayed 'pending' and were re-delegated on
                # every fire (the duplicate Faith-module PR bug, #1551/#1553).
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """UPDATE unified_tasks SET status = 'in_progress',
                               delegation_args = COALESCE(delegation_args, '{}'::jsonb)
                                   || jsonb_build_object('codex_queued_delegate_id', %s)
                           WHERE id = %s""",
                        (result.get("task_id"), task["id"]),
                    )
                logger.info(
                    "codex_auto_queue: queued task #%s '%s' (project %s '%s') → delegate task #%s (source marked in_progress)",
                    task["id"],
                    task["title"],
                    task["project_id"],
                    task.get("project_name", ""),
                    result.get("task_id"),
                )
            else:
                logger.warning("codex_auto_queue: delegate_task failed: %s", result.get("error"))

        except Exception as e:
            logger.error("codex_auto_queue failed: %s", e)

    # ------------------------------------------------------------------
    # C.O.D.E.X. Event Auto-Documentation (Project #272 Phase 2 / Task #2108)
    # ------------------------------------------------------------------

    def _run_codex_event_docs(self):
        """Scan for undocumented project_decisions and auto-write vault_notes.

        Template-based (no LLM dispatch) so the job is cheap and safe to
        run every 30 min. Writes new ``knowledge_base`` rows with
        ``source_type='codex_event_doc'`` and ``source_id='decision:<id>'``
        — the service dedups on these before inserting, so the job is
        idempotent.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.codex_event_docs_service import (
                format_alert_message,
                run_event_auto_docs,
            )

            result = run_event_auto_docs(max_items_per_run=10)
            severity = result["severity"]
            metrics = result["summary_metrics"]
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="codex_event_docs",
                items_processed=metrics["created"],
                items_failed=metrics["failed"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "reasons": result.get("reasons", []),
                    "lookback_days": result.get("lookback_days"),
                },
            )

            # We intentionally stay quiet on success — routine auto-doc
            # runs are uninteresting. Only surface on failure.
            if severity == "warning" and metrics["failed"] > 0:
                body = format_alert_message(result)
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "warning",
                            "C.O.D.E.X. — auto-doc failures",
                            body,
                            "codex",
                            "normal",
                            "📚",
                            "/tools/consciousness#knowledge",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as notify_err:
                    logger.warning(
                        "C.O.D.E.X. docs: system_notifications insert failed: %s",
                        notify_err,
                    )

            logger.info(
                "C.O.D.E.X. auto-docs: created=%d failed=%d in %dms",
                metrics["created"],
                metrics["failed"],
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("C.O.D.E.X. auto-docs failed: %s", e)
            try:
                self._log_cycle(
                    job_name="codex_event_docs",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # R.E.S.O.L.V.E. Email Oversight (Task #2490)
    # ------------------------------------------------------------------

    def _run_resolve_oversight(self):
        """Scan for unanswered inbound emails, assign to R.E.S.O.L.V.E., create tickets."""
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.email_manager.hq_routes import run_resolve_oversight

            result = run_resolve_oversight(threshold_hours=24)
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle(
                job_name="resolve_email_oversight",
                items_processed=result["scanned"],
                items_failed=0,
                duration_ms=duration_ms,
                details=result,
            )
            logger.info(
                "R.E.S.O.L.V.E. oversight: scanned=%d flagged=%d tickets=%d in %dms",
                result["scanned"],
                result["flagged"],
                result["tickets_created"],
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("R.E.S.O.L.V.E. oversight failed: %s", e)
            try:
                self._log_cycle(
                    job_name="resolve_email_oversight",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # V.I.G.I.L. Infrastructure Heartbeat (Project #272 Phase 2 / Task #2127)
    # ------------------------------------------------------------------

    def _run_dns_monitor(self):
        """Every-2-min external-DNS resolution probe (Task #4571).

        Catches the recurring OAuth/platform.claude.com failure live: probes each
        watched name against AdGuard + a control upstream and persists evidence to
        dns_probe_log. Telegram fires ONLY when the classification CHANGES (entering
        a failing state, or recovering to healthy) so it never floods.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.dns_monitor_service import format_dns_alert, run_dns_probe

            out = run_dns_probe()
            severity = out["severity"]
            failed = sum(1 for r in out["results"] if r["status"] != "healthy")
            passed = len(out["results"]) - failed
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="vigil_dns_monitor",
                items_processed=passed,
                items_failed=failed,
                duration_ms=duration_ms,
                details={
                    "classification": out["classification"],
                    "severity": severity,
                    "ip_forward": out["ip_forward"],
                    "notes": out["notes"],
                },
            )

            # system_notifications row — surfaces the DNS fault in the platform UI.
            if severity in ("warning", "error"):
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"V.I.G.I.L. — DNS {out['classification']}",
                            format_dns_alert(out),
                            "vigil",
                            "high" if severity == "error" else "normal",
                            "🌐",
                            "/tools/security-network",
                            "all",
                            None,
                            psycopg2.extras.Json({"classification": out["classification"]}),
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as notify_err:
                    logger.warning("dns_monitor: system_notifications insert failed: %s", notify_err)

            # Telegram only on classification CHANGE — entering a failing state OR
            # recovering from one. The first healthy baseline stays silent.
            if out["classification"] != self._last_dns_class:
                entering_fail = out["classification"] != "healthy"
                recovering = out["classification"] == "healthy" and self._last_dns_class != "healthy"
                if entering_fail or recovering:
                    try:
                        self._send_telegram(format_dns_alert(out))
                    except Exception as tg_err:
                        logger.warning("dns_monitor: Telegram dispatch failed: %s", tg_err)
                self._last_dns_class = out["classification"]
        except Exception as exc:
            logger.error("dns_monitor cycle failed: %s", exc)

    def _run_infra_heartbeat(self):
        """Every-5-min heartbeat over critical infrastructure containers.

        Detects absent / stopped / unreachable containers (the NPM
        removal failure mode from 2026-04-18). For each DOWN container
        where ``auto_restart_safe=True``, files a Tier-2 approval via
        ``request_approval(action_type='restart_container', ...)`` so
        Kytran approves the recovery from Telegram.
        """
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.infra_heartbeat_service import (
                check_all_critical,
                format_alert_message,
            )

            result = check_all_critical()
            severity = result["severity"]
            metrics = result["summary_metrics"]
            duration_ms = int((time.time() - start) * 1000)

            self._log_cycle(
                job_name="vigil_infra_heartbeat",
                items_processed=metrics["healthy"],
                items_failed=metrics["down"] + metrics["warnings"],
                duration_ms=duration_ms,
                details={
                    "severity": severity,
                    "summary_metrics": metrics,
                    "down_names": result["down_names"],
                    "warning_names": result["warning_names"],
                    "reasons": result.get("reasons", []),
                },
            )

            if severity in ("warning", "error"):
                body = format_alert_message(result)
                # system_notifications row — surfaces in platform UI
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                          (type, title, message, source, priority, source_icon,
                           related_action, visibility, target_user_id, is_read,
                           metadata, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, NOW())
                        """,
                        (
                            "alert" if severity == "error" else "warning",
                            f"V.I.G.I.L. — {severity} in infra heartbeat",
                            body,
                            "vigil",
                            "high" if severity == "error" else "normal",
                            "🛡️",
                            "/tools/security-network",
                            "all",
                            None,
                            psycopg2.extras.Json(metrics),
                        ),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as notify_err:
                    logger.warning(
                        "V.I.G.I.L. heartbeat: system_notifications insert failed: %s",
                        notify_err,
                    )

            # Telegram only when DOWN set changes (new failure or recovery).
            # Prevents flooding when a container stays down across many 5-min ticks.
            current_down = frozenset(result["down_names"])
            if current_down != self._last_down_set:
                try:
                    self._send_telegram(format_alert_message(result))
                except Exception as tg_err:
                    logger.warning("V.I.G.I.L. heartbeat: Telegram dispatch failed: %s", tg_err)
                self._last_down_set = current_down

            # File Tier-2 restart approvals for each auto_restart_safe DOWN
            # container. request_approval de-dups per action_type+agent, so
            # we won't pile up duplicates across runs.
            for record in result["containers"]:
                if record["severity"] != "error":
                    continue
                if not record.get("auto_restart_safe"):
                    continue
                try:
                    approval_id = request_approval(
                        action_type="restart_container",
                        action_data={
                            "agent": record["name"],  # dedup key
                            "compose_service": record["compose_service"],
                            "container": record["name"],
                            "reason": record.get("reason") or "heartbeat DOWN",
                            "recent_events": record.get("recent_events", [])[:5],
                        },
                        reason=(
                            f"Container {record['name']} is {record['reason']}. "
                            f"Auto-restart via docker compose is configured as "
                            f"safe. Approve to bring it back up."
                        ),
                        requested_by="vigil_infra_heartbeat",
                        tier=2,
                    )
                    if approval_id:
                        logger.info(
                            "V.I.G.I.L. heartbeat: restart approval #%s filed for %s",
                            approval_id,
                            record["name"],
                        )
                except Exception as appr_err:
                    logger.warning(
                        "V.I.G.I.L. heartbeat: approval submission failed for %s: %s",
                        record["name"],
                        appr_err,
                    )

            logger.info(
                "V.I.G.I.L. infra heartbeat: severity=%s down=%d warnings=%d in %dms",
                severity,
                metrics["down"],
                metrics["warnings"],
                duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("V.I.G.I.L. infra heartbeat failed: %s", e)
            try:
                self._log_cycle(
                    job_name="vigil_infra_heartbeat",
                    items_processed=0,
                    items_failed=1,
                    duration_ms=duration_ms,
                    error_message=str(e),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DDNS Public IP Monitor
    # ------------------------------------------------------------------

    def _check_ddns(self):
        """Check public IP every 15 min. On change, log + update Hostinger DNS."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.saas_manager.ip_monitor import check_and_update_ip

            result = check_and_update_ip()

            if result.get("changed"):
                old = result.get("old_ip", "unknown")
                new = result.get("current_ip", "unknown")
                updated = result.get("updated_domains", [])
                msg = f"\U0001f310 *Public IP Changed*\n\n" f"`{old}` \u2192 `{new}`\n"
                if updated:
                    msg += f"\nUpdated DNS: {', '.join(updated)}"
                else:
                    msg += "\n\u26a0\ufe0f DNS auto-update failed — check Hostinger manually"

                self._send_telegram(msg)
                self._create_network_alert(
                    "ip_changed",
                    "high",
                    "ddns_monitor",
                    f"Public IP changed: {old} → {new}",
                    {"old_ip": old, "new_ip": new, "updated_domains": updated},
                )
                logger.warning("DDNS: Public IP changed %s -> %s", old, new)
            else:
                logger.debug("DDNS: IP unchanged (%s)", result.get("current_ip"))

        except Exception as e:
            logger.error("DDNS check failed: %s", e)

    # ------------------------------------------------------------------
    # V.I.G.I.L.: VPN Usage Monitor
    # ------------------------------------------------------------------

    def _vigilil_vpn_scan(self):
        """Scan ntopng flows for VPN/tunnel traffic every 5 min."""
        try:
            import os
            import sys

            import requests as _req

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from database import get_db_cursor

            nt_host = os.getenv("NTOPNG_HOST", "192.168.1.200")
            nt_port = os.getenv("NTOPNG_PORT", "3001")
            nt_user = os.getenv("NTOPNG_USER", "admin")
            nt_pass = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))

            VPN_L7 = {
                "OpenVPN",
                "WireGuard",
                "IPSec",
                "PPTP",
                "L2TP",
                "Tor",
                "SOCKS",
                "SoftEther",
                "Tailscale",
            }
            VPN_L7_PARTIAL = [
                "Tailscale",
                "NordVPN",
                "ExpressVPN",
                "Surfshark",
                "ProtonVPN",
                "Mullvad",
            ]

            ns = _req.Session()
            ns.post(
                f"http://{nt_host}:{nt_port}/authorize.html",
                data={"user": nt_user, "password": nt_pass},
                allow_redirects=True,
                timeout=3,
            )
            fr = ns.get(
                f"http://{nt_host}:{nt_port}/lua/rest/v2/get/flow/active.lua",
                params={"ifid": 0, "currentPage": 1, "perPage": 500},
                timeout=5,
            )
            if fr.status_code != 200:
                return

            # ntopng returns HTML (login page) when session auth silently fails;
            # guard JSON decode so the job logs one "auth failed" debug line
            # instead of a JSONDecodeError traceback every 5 min.
            ct = fr.headers.get("content-type", "")
            if "json" not in ct.lower():
                logger.debug("V.I.G.I.L. VPN scan: ntopng returned non-JSON (%s) — session auth likely failed", ct)
                return
            try:
                raw = fr.json()
            except ValueError:
                logger.debug("V.I.G.I.L. VPN scan: ntopng response not valid JSON, skipping")
                return
            flows = raw.get("rsp", {})
            if isinstance(flows, dict):
                flows = flows.get("data", [])
            if not isinstance(flows, list):
                return

            vpn_devices = {}
            for flow in flows:
                proto = flow.get("protocol", {})
                l7 = proto.get("l7", "")
                is_vpn = l7 in VPN_L7 or any(v in l7 for v in VPN_L7_PARTIAL)
                if not is_vpn:
                    srv_port = flow.get("server", {}).get("port", 0)
                    cli_port = flow.get("client", {}).get("port", 0)
                    VPN_PORTS = {1194, 500, 4500, 51820, 1723}
                    is_vpn = srv_port in VPN_PORTS or cli_port in VPN_PORTS

                if is_vpn:
                    cli_ip = flow.get("client", {}).get("ip", "?")
                    if cli_ip.startswith("192.168."):
                        if cli_ip not in vpn_devices:
                            vpn_devices[cli_ip] = {"protocols": set(), "bytes": 0}
                        vpn_devices[cli_ip]["protocols"].add(l7)
                        vpn_devices[cli_ip]["bytes"] += flow.get("bytes", 0)

            # Alert on NEW VPN devices (not already alerted in last hour)
            for ip, info in vpn_devices.items():
                protos = ", ".join(info["protocols"])
                # Resolve label
                label = ip
                try:
                    with get_db_cursor() as (conn, cur):
                        cur.execute(
                            """SELECT COALESCE(ndu.user_name, ndu.device_label) as label
                               FROM network_traffic_stats nts
                               LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                               WHERE nts.device_ip = %s LIMIT 1""",
                            (ip,),
                        )
                        row = cur.fetchone()
                        if row and row["label"]:
                            label = row["label"]

                        # Dedup: skip if alerted in last hour
                        cur.execute(
                            """SELECT id FROM network_alerts
                               WHERE alert_type = 'vpn_detected' AND source = 'vpn_monitor'
                               AND details->>'ip' = %s AND created_at > NOW() - INTERVAL '1 hour'""",
                            (ip,),
                        )
                        if cur.fetchone():
                            continue
                except Exception:
                    pass

                self._create_network_alert(
                    "vpn_detected",
                    "medium",
                    "vpn_monitor",
                    f"VPN traffic detected: {label} ({ip}) using {protos}",
                    {"ip": ip, "label": label, "protocols": list(info["protocols"]), "bytes": info["bytes"]},
                )

        except Exception as e:
            logger.error("V.I.G.I.L. VPN scan failed: %s", e)

    # ------------------------------------------------------------------
    # V.I.G.I.L.: Bandwidth Threshold Monitor
    # ------------------------------------------------------------------

    def _vigilil_bandwidth_alerts(self):
        """Check per-device bandwidth and alert on heavy consumers (>10GB/24h)."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from database import get_db_cursor

            THRESHOLD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB

            with get_db_cursor() as (conn, cur):
                # Use delta calculation — bytes are cumulative from ntopng
                cur.execute(
                    """WITH deltas AS (
                        SELECT device_ip, device_mac, hour_bucket,
                               bytes_in - COALESCE(
                                   LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0
                               ) AS delta_in,
                               bytes_out - COALESCE(
                                   LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0
                               ) AS delta_out
                        FROM network_traffic_stats
                    )
                    SELECT d.device_ip,
                           COALESCE(ndu.user_name, ndu.device_label, d.device_ip) as label,
                           SUM(GREATEST(d.delta_in, 0) + GREATEST(d.delta_out, 0)) as total
                    FROM deltas d
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = d.device_mac
                    WHERE d.hour_bucket >= NOW() - INTERVAL '24 hours'
                    GROUP BY d.device_ip, label
                    HAVING SUM(GREATEST(d.delta_in, 0) + GREATEST(d.delta_out, 0)) > %s
                    ORDER BY total DESC""",
                    (THRESHOLD_BYTES,),
                )
                heavy = [dict(r) for r in cur.fetchall()]

                for dev in heavy:
                    ip = dev["device_ip"]
                    total_gb = round(dev["total"] / (1024**3), 1)
                    label = dev["label"] or ip

                    # Dedup: skip if alerted in last 6 hours
                    cur.execute(
                        """SELECT id FROM network_alerts
                           WHERE alert_type = 'bandwidth_exceeded' AND source = 'bandwidth_monitor'
                           AND details->>'ip' = %s AND created_at > NOW() - INTERVAL '6 hours'""",
                        (ip,),
                    )
                    if cur.fetchone():
                        continue

                    self._create_network_alert(
                        "bandwidth_exceeded",
                        "medium",
                        "bandwidth_monitor",
                        f"High bandwidth: {label} used {total_gb} GB in 24h",
                        {"ip": ip, "label": label, "total_bytes": dev["total"], "total_gb": total_gb},
                    )

        except Exception as e:
            logger.error("V.I.G.I.L. bandwidth alerts failed: %s", e)

    # ------------------------------------------------------------------
    # HR Tracker (Project #91 — Phase 7)
    # ------------------------------------------------------------------

    def _run_ethics_monitoring(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py run_ethics_monitoring()
        Run C.R.E.E.D. ethics monitoring cycle (every 15 min).

        Managed by V.I.G.I.L. (Security & Compliance director).
        Results visible in Department HQ + C.R.E.E.D. institute page.
        """
        pass

    # ------------------------------------------------------------------
    # Migrated from consciousness_scheduler (centralized into Autonomy)
    # ------------------------------------------------------------------

    def _conversation_consolidation(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py conversation_consolidation()"""
        pass

    def _improvement_detection(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py improvement_detection()"""
        pass

    def _daily_self_reflection(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py daily_self_reflection()"""
        pass

    def _weekly_memory_consolidation(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py weekly_memory_consolidation()"""
        pass

    # ------------------------------------------------------------------
    # Migrated from infrastructure scheduler (app.py) — fully centralized
    # ------------------------------------------------------------------

    def _batch_medium_issues(self):
        """Weekly code issue batch (Sun 2AM) — migrated from app.py."""
        start = time.time()
        try:
            from services.scan_pipeline import batch_medium_issues

            result = batch_medium_issues()
            duration_ms = int((time.time() - start) * 1000)
            processed = result.get("proposals_created", 0) if isinstance(result, dict) else 0
            self._log_cycle("batch_medium_issues", processed, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("batch_medium_issues", 0, 1, duration_ms, error_message=str(e))

    def _auto_log_ingestion(self):
        """Auto-ingest conversation logs every 30 min — migrated from app.py."""
        start = time.time()
        try:
            from tools.consciousness.log_ingestor import batch_ingest_logs

            result = batch_ingest_logs(limit=100)
            duration_ms = int((time.time() - start) * 1000)
            created = result.get("created", 0) if isinstance(result, dict) else 0
            if created > 0:
                logger.info(f"Auto-ingested {created} conversation logs")
            self._log_cycle("auto_log_ingestion", created, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("auto_log_ingestion", 0, 1, duration_ms, error_message=str(e))

    def _weekly_dependency_scan(self):
        """Weekly dependency scan (Sun 4AM) — migrated from app.py."""
        start = time.time()
        try:
            import base64
            import requests
            from tools.consciousness.dependency_scanner import DependencyScanner
            from tools.consciousness.github_routes import _store_dependency_scan
            from database import get_db_cursor

            github_token = os.getenv("GITHUB_TOKEN")
            if not github_token:
                try:
                    with open("/mnt/archie_brain/secrets/api/github_token.txt", "r") as f:
                        github_token = f.read().strip()
                except FileNotFoundError:
                    pass

            scanner = DependencyScanner(github_token=github_token)
            headers = {}
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"
                headers["Accept"] = "application/vnd.github.v3+json"

            total_scans = 0
            total_entries = 0

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("SELECT id, repo_name FROM github_repositories WHERE status IN ('cloned', 'indexed')")
                repos = cur.fetchall()

                for repo in repos:
                    owner_repo = repo["repo_name"]
                    for dep_file in ["package.json", "requirements.txt"]:
                        try:
                            resp = requests.get(
                                f"https://api.github.com/repos/{owner_repo}/contents/{dep_file}",
                                headers=headers,
                                timeout=10,
                            )
                            if resp.status_code != 200:
                                continue
                            content = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
                            scan = scanner.scan_dependency_file(content, dep_file, owner_repo)
                            # Per-file SAVEPOINT: a single failing INSERT must not poison
                            # the shared txn and silently roll back the final commit while
                            # the in-memory count is logged as SUCCESS (KB #270009 class).
                            cur.execute("SAVEPOINT dep_scan")
                            try:
                                total_entries += _store_dependency_scan(cur, scan)
                                cur.execute("RELEASE SAVEPOINT dep_scan")
                                total_scans += 1
                            except Exception as e_store:
                                cur.execute("ROLLBACK TO SAVEPOINT dep_scan")
                                logger.warning(f"Dep scan store failed for {owner_repo}/{dep_file}: {e_store}")
                        except Exception as e:
                            logger.warning(f"Dep scan failed for {owner_repo}/{dep_file}: {e}")

                # Local platform requirements.txt
                try:
                    with open("/app/requirements.txt", "r") as f:
                        content = f.read()
                    scan = scanner.scan_dependency_file(content, "requirements.txt", "local/platform_v2")
                    total_entries += _store_dependency_scan(cur, scan)
                    total_scans += 1
                except Exception as e:
                    logger.warning(f"Dep scan failed for local requirements: {e}")

            duration_ms = int((time.time() - start) * 1000)
            logger.info(f"Weekly dep scan: {total_scans} files, {total_entries} suggestions")
            self._log_cycle(
                "weekly_dependency_scan",
                total_scans,
                0,
                duration_ms,
                details={"files_scanned": total_scans, "entries_stored": total_entries},
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("weekly_dependency_scan", 0, 1, duration_ms, error_message=str(e))

    def _health_probe(self):
        """Service health probe every 15 min — migrated from app.py."""
        start = time.time()
        try:
            from tools.consciousness.devhq_routes import _run_and_store_health_check

            _run_and_store_health_check()
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("health_probe", 1, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("health_probe", 0, 1, duration_ms, error_message=str(e))

    def _crew_wellness_tick(self):
        """Crew wellness tick every 5 min — migrated from app.py."""
        start = time.time()
        try:
            from app import crew_wellness_tick

            crew_wellness_tick(self.flask_app)
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("crew_wellness_tick", 1, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("crew_wellness_tick", 0, 1, duration_ms, error_message=str(e))

    def _ollama_model_health(self):
        """Ollama model health check every 30 min — migrated from app.py."""
        start = time.time()
        try:
            import requests as req
            import psutil

            ollama_host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
            if not ollama_host.startswith("http"):
                ollama_host = f"http://{ollama_host}"

            from app import _get_agent_models

            desired = {}
            for model_name, endpoint in _get_agent_models():
                desired[model_name] = endpoint

            resp = req.get(f"{ollama_host}/api/ps", timeout=10)
            if resp.status_code != 200:
                self._log_cycle("ollama_model_health", 0, 0, int((time.time() - start) * 1000))
                return
            ps_models = resp.json().get("models", [])
            loaded = {m["name"] for m in ps_models}
            gpu_models = set()
            for m in ps_models:
                if m.get("size_vram", 0) > 0:
                    gpu_models.add(m["name"])
                    gpu_models.add(m["name"].replace(":latest", ""))

            # CPU-tier models are NOT proactively warmed — they load on demand via
            # dispatch_pending_queue. Keeping them pre-loaded pins 20-40GB of RAM
            # between tasks, crowding out concurrent agents. They cold-load in
            # 30-600s when needed; that latency is acceptable (user decision).
            # Only small GPU-tier models (≤3B, fit in VRAM) stay warm — their
            # cold-load is ~3-10s so proactive warmup is still worth the VRAM.
            _CPU_TIER_NO_WARMUP = {
                "mistral:7b",
                "gemma3:12b",
                "dolphin3:latest",
                "qwen2.5-coder:7b",
                "phi4:14b",
                "deepseek-coder-v2:16b",
                "qwen3-coder-cpu:latest",
                "qwen2.5:7b",
            }
            desired = {m: ep for m, ep in desired.items() if m not in _CPU_TIER_NO_WARMUP}

            # Cap to top 3 GPU/embed models — small warm set, minimal VRAM footprint.
            HEALTH_WARM_CAP = 3
            desired_capped = dict(list(desired.items())[:HEALTH_WARM_CAP])

            missing = {m for m in desired_capped if m not in loaded and f"{m}:latest" not in loaded}
            if not missing:
                self._log_cycle("ollama_model_health", len(loaded), 0, int((time.time() - start) * 1000))
                return

            ram_free = psutil.virtual_memory().available / (1024**3)
            reloaded = 0
            actual_failed = 0
            deferred = 0  # warm POSTs that timed out because the hub queue was busy — not real failures
            for model_name in list(missing):
                ram_free = psutil.virtual_memory().available / (1024**3)
                if ram_free < 10:
                    break
                endpoint = desired_capped[model_name]
                use_gpu = model_name in gpu_models or f"{model_name}:latest" in gpu_models
                try:
                    # keep_alive="5m" — GPU/embed models only reach this point
                    # (CPU-tier filtered above). 5m is enough to absorb burst
                    # traffic on small agents without pinning VRAM long-term;
                    # frees VRAM between idle periods so more concurrent models
                    # can warm-boot on demand.
                    if endpoint == "embed":
                        data = {"model": model_name, "input": "health", "keep_alive": "5m"}
                    else:
                        opts = {"num_predict": 1}
                        if not use_gpu:
                            opts["num_gpu"] = 0
                        data = {
                            "model": model_name,
                            "prompt": "health",
                            "stream": False,
                            "options": opts,
                            "keep_alive": "5m",
                        }
                    # 90s timeout for most models, 180s for coder models.
                    # Concurrent Ollama inference (quality scorer, dispatch) can cause
                    # contention; failures are retried next 30-min cycle.
                    # Big CPU-tier models (gemma3:12b, mistral:7b, dolphin3, coder)
                    # cold-load into RAM (num_gpu=0 above) and take far longer than
                    # 90s on the hub — give them 600s so the keep-warm actually
                    # succeeds instead of false-failing every cycle (KB #270009).
                    _BIG_CPU_TIER = {
                        "mistral:7b",
                        "gemma3:12b",
                        "dolphin3:latest",
                        "qwen2.5-coder:7b",
                        "phi4:14b",
                        "deepseek-coder-v2:16b",
                        "qwen3-coder-cpu:latest",
                    }
                    if model_name in _BIG_CPU_TIER or "coder" in model_name:
                        timeout = 600
                    else:
                        timeout = 90
                    r = req.post(f"{ollama_host}/api/{endpoint}", json=data, timeout=timeout)
                    if r.status_code == 200:
                        reloaded += 1
                    else:
                        actual_failed += 1
                        logger.warning(f"Ollama health: {model_name} returned {r.status_code}")
                except req.exceptions.Timeout:
                    # Warm-load timed out waiting on the hub Ollama queue, which
                    # serializes on NUM_PARALLEL=1 and is frequently mid-flight on a
                    # multi-minute generation (translation drainage + WTF traffic).
                    # This is contention, NOT a model health failure — on-demand
                    # dispatch to these models still succeeds (e.g. mistral:7b is
                    # 100% success in task_execution_log). Counting it as a failure
                    # false-alarms the boot anomaly list every busy cycle, which led
                    # to a wasted VRAM-drift misdiagnosis. Defer instead. (KB #270033)
                    deferred += 1
                    logger.info(f"Ollama health: {model_name} warm deferred (hub busy)")
                except Exception as e:
                    actual_failed += 1
                    logger.warning(f"Ollama health: {model_name} failed: {e}")

            duration_ms = int((time.time() - start) * 1000)
            # items_failed = actual load failures only. Warm-POST timeouts under a
            # busy hub queue are counted as `deferred`, not failed, so a contended
            # hub doesn't false-error every cycle (KB #270033). details surfaces the
            # full warm set size + deferred count for context.
            self._log_cycle(
                "ollama_model_health",
                reloaded,
                actual_failed,
                duration_ms,
                details={
                    "missing": len(missing),
                    "reloaded": reloaded,
                    "actual_failed": actual_failed,
                    "deferred_busy": deferred,
                    "total_desired": len(desired),
                    "warm_cap": HEALTH_WARM_CAP,
                },
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("ollama_model_health", 0, 1, duration_ms, error_message=str(e))

    def _ollama_placement_telemetry(self):
        """5-min placement-decision summary. Writes one autonomy_loop_log row."""
        start = time.time()
        try:
            # Import lazily — keeps agent_loop importable even if dept_hq.services
            # is temporarily broken during a refactor.
            from tools.department_hq.services.ollama_options import drain_placement_events

            events = drain_placement_events()
            if not events:
                self._log_cycle(
                    "ollama_placement_telemetry",
                    0,
                    0,
                    int((time.time() - start) * 1000),
                )
                return

            gpu = sum(1 for e in events if e.get("placement") == "gpu")
            cpu = sum(1 for e in events if e.get("placement") == "cpu")
            total = gpu + cpu
            cpu_share = cpu / max(total, 1)

            prev = getattr(self, "_last_placement_summary", None)
            anomaly = cpu_share > 0.5 and prev is not None and prev.get("cpu_share", 0) > 0.5
            self._last_placement_summary = {
                "ts": time.time(),
                "gpu": gpu,
                "cpu": cpu,
                "cpu_share": cpu_share,
            }

            self._log_cycle(
                "ollama_placement_telemetry",
                items_processed=total,
                items_failed=cpu if anomaly else 0,
                duration_ms=int((time.time() - start) * 1000),
                error_message=(f"sustained_cpu_fallback cpu_share={cpu_share:.2f}" if anomaly else None),
            )
        except Exception as e:
            logger.error(f"ollama_placement_telemetry failed: {e}")
            self._log_cycle(
                "ollama_placement_telemetry",
                0,
                1,
                int((time.time() - start) * 1000),
                error_message=str(e),
            )

    def _write_scheduler_heartbeat(self):
        """Write a row to scheduler_heartbeat every 30s.

        Path C (decision_id 557): the scheduler runs in a sidecar container
        in production, so HTTP routes can no longer read
        ``app.config["AGENT_LOOP"].running`` (the in-process Python object
        lives in another process). They consume this table instead.

        Also prunes rows older than 24h so the table stays bounded.
        """
        try:
            import socket
            from database import get_db_cursor
            from psycopg2.extras import Json

            scheduler = self.scheduler
            jobs = scheduler.get_jobs() if scheduler else []
            jobs_total = len(jobs)
            running = bool(scheduler and getattr(scheduler, "running", False))
            next_run = None
            jobs_summary = []
            for j in jobs:
                nr = getattr(j, "next_run_time", None)
                if nr and (next_run is None or nr < next_run):
                    next_run = nr
                jobs_summary.append(
                    {
                        "id": j.id,
                        "name": j.name or j.id,
                        "next_run": nr.isoformat() if nr else None,
                        "trigger": str(j.trigger) if j.trigger else "",
                    }
                )

            details = {
                "source": "agent_loop",
                "jobs": jobs_summary,
            }

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO scheduler_heartbeat
                        (hostname, ts, running, jobs_total, jobs_pending, next_run_ts, details)
                    VALUES (%s, now(), %s, %s, %s, %s, %s)
                    """,
                    (
                        socket.gethostname(),
                        running,
                        jobs_total,
                        0,  # jobs_pending — APScheduler doesn't track this directly
                        next_run,
                        Json(details),
                    ),
                )
                # Bounded retention — heartbeats are diagnostic, not historical
                cur.execute("DELETE FROM scheduler_heartbeat WHERE ts < now() - interval '24 hours'")
        except Exception as e:
            logger.warning("scheduler_heartbeat write failed: %s", e)

    def _platform_watchdog(self):
        """Alert when host is under memory/CPU pressure.

        Project #240 task #1760 — fires every 2 min.
        Thresholds: load1 > 30, MemAvailable < 5GB, SwapFree < 500MB.
        Dedup: one alert per category per 1 hour (#2233 — was 15 min, caused Telegram flood).
        """
        start = time.time()
        try:
            import psutil

            with open("/proc/loadavg") as f:
                load1 = float(f.read().split()[0])
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
            mem_avail_gb = vm.available / (1024**3)
            swap_free_gb = (sw.total - sw.used) / (1024**3)

            now = time.time()
            if not hasattr(self, "_watchdog_last_alert"):
                self._watchdog_last_alert = {}
            dedup_s = 3600  # 1 hour between repeated alerts for same condition (#2233)

            triggered = []
            if load1 > 30 and now - self._watchdog_last_alert.get("load", 0) > dedup_s:
                triggered.append(("load", f"load1={load1:.1f} (threshold 30)"))
                self._watchdog_last_alert["load"] = now
            if mem_avail_gb < 5 and now - self._watchdog_last_alert.get("mem", 0) > dedup_s:
                triggered.append(("mem", f"MemAvailable={mem_avail_gb:.1f}GB (threshold 5GB)"))
                self._watchdog_last_alert["mem"] = now
            if swap_free_gb < 0.5 and now - self._watchdog_last_alert.get("swap", 0) > dedup_s:
                triggered.append(("swap", f"SwapFree={swap_free_gb:.2f}GB (threshold 0.5GB)"))
                self._watchdog_last_alert["swap"] = now

            # Backup freshness (Phase 5 / Task 19 of backup system redesign).
            # Alert if no successful primary backup in the last 36h.
            try:
                from database import get_db_cursor
                from datetime import datetime as _dt

                with get_db_cursor() as (_c, _cur):
                    _cur.execute(
                        "SELECT MAX(created_at) AS latest FROM backup_log WHERE status='success' AND tier='primary'"
                    )
                    _row = _cur.fetchone()
                latest = _row["latest"] if _row else None
                if latest is None:
                    if now - self._watchdog_last_alert.get("backup_missing", 0) > dedup_s:
                        triggered.append(
                            ("backup_missing", "No successful primary backups recorded (empty backup_log)")
                        )
                        self._watchdog_last_alert["backup_missing"] = now
                else:
                    latest_naive = (
                        latest.replace(tzinfo=None) if hasattr(latest, "tzinfo") and latest.tzinfo else latest
                    )
                    age_h = (_dt.utcnow() - latest_naive).total_seconds() / 3600
                    if age_h > 36 and now - self._watchdog_last_alert.get("backup_stale", 0) > dedup_s:
                        triggered.append(("backup_stale", f"Last primary backup {age_h:.1f}h ago (threshold 36h)"))
                        self._watchdog_last_alert["backup_stale"] = now
            except Exception as _be:
                logger.warning(f"watchdog backup-freshness check failed: {_be}")

            # Backup-tier disk free (<20% alerts).
            try:
                import shutil as _sh

                for _name, _path in [("primary", "/mnt/data2"), ("usb", "/mnt/external-backup")]:
                    try:
                        _u = _sh.disk_usage(_path)
                        _pct_free = 100.0 * _u.free / _u.total
                        _key = f"disk_{_name}"
                        if _pct_free < 20 and now - self._watchdog_last_alert.get(_key, 0) > dedup_s:
                            triggered.append((_key, f"Backup disk {_name} ({_path}) {_pct_free:.1f}% free (<20%)"))
                            self._watchdog_last_alert[_key] = now
                    except FileNotFoundError:
                        _key = f"disk_{_name}_missing"
                        if now - self._watchdog_last_alert.get(_key, 0) > dedup_s:
                            triggered.append((_key, f"Backup mount missing: {_path}"))
                            self._watchdog_last_alert[_key] = now
            except Exception as _de:
                logger.warning(f"watchdog disk-free check failed: {_de}")

            # Backup tier health — warn if any offsite tier has no successful sync in >14 days
            # (Phase 6 / Task 4 of backup completion plan).
            try:
                from database import get_db_cursor

                with get_db_cursor() as (_c, _cur):
                    _cur.execute(
                        "SELECT tier, "
                        "       EXTRACT(EPOCH FROM (NOW() - MAX(CASE WHEN status='success' "
                        "                                            THEN created_at END))) / 86400.0 "
                        "       AS days_since_success "
                        "FROM backup_log "
                        "WHERE tier IN ('usb', 'gdrive', 'vps') "
                        "GROUP BY tier"
                    )
                    _rows = _cur.fetchall()
                _stale_tiers = [
                    (r["tier"], r["days_since_success"])
                    for r in _rows
                    if r["days_since_success"] is None or r["days_since_success"] > 14
                ]
                if _stale_tiers:
                    _key = "backup_tier_health"
                    if now - self._watchdog_last_alert.get(_key, 0) > dedup_s:
                        _details = ", ".join(
                            f"{_t}={'never' if _d is None else f'{_d:.1f}d'}" for _t, _d in _stale_tiers
                        )
                        triggered.append((_key, f"Backup tiers stale (>14d): {_details}"))
                        self._watchdog_last_alert[_key] = now
            except Exception as _te:
                logger.warning(f"watchdog tier-health check failed: {_te}")

            # WTF ingest-freshness — the wtf-ingest worker runs on boston-2 but writes to
            # the hub `wtf` DB; a silent crash (e.g. a bad row) freezes the front page with
            # NO self-report (it happened 2026-07-14). Check externally: alert if no new
            # article in >90 min. Sends its own interactive alert directly. (#4890)
            try:
                import psycopg2 as _pg

                from database import _get_db_password

                _wc = _pg.connect(
                    host=os.getenv("DB_HOST", "192.168.1.200"),
                    port=int(os.getenv("DB_PORT", "5432")),
                    dbname="wtf",
                    user=os.getenv("DB_USER", "archie"),
                    password=_get_db_password(),  # DB_PASSWORD is a Docker secret, not an env var
                    connect_timeout=8,
                )
                try:
                    with _wc.cursor() as _wcur:
                        _wcur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - MAX(ingested_at))) / 60.0 FROM wtf.articles")
                        _wrow = _wcur.fetchone()
                        # Coverage check on the SETTLED cohort (24-48h old — workers had a
                        # full day to process it). beat IS NOT NULL = processed ('none' is
                        # the legit no-match sentinel). Guards against the classifier
                        # silently under-sweeping again (#4897 — coverage sat at 8-27%
                        # for weeks with zero alerts).
                        _wcur.execute(
                            "SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE beat IS NOT NULL) "
                            "/ GREATEST(COUNT(*), 1), 1) "
                            "FROM wtf.articles "
                            "WHERE ingested_at BETWEEN NOW() - INTERVAL '48 hours' "
                            "AND NOW() - INTERVAL '24 hours'"
                        )
                        _crow = _wcur.fetchone()
                    _wtf_gap = _wrow[0] if _wrow else None
                    _beat_cov = float(_crow[0]) if _crow and _crow[0] is not None else None
                finally:
                    _wc.close()
                if (
                    _wtf_gap is not None
                    and _wtf_gap > 90
                    and now - self._watchdog_last_alert.get("wtf_ingest_stale", 0) > dedup_s
                ):
                    self._watchdog_last_alert["wtf_ingest_stale"] = now
                    from services.alert_actions_service import send_alert

                    send_alert(
                        alert_key="wtf_ingest_stale",
                        title="⚠️ WTF ingest stalled",
                        message=(
                            f"what-the-fact.com: newest article is {_wtf_gap:.0f} min old "
                            f"(threshold 90m). The front page may be frozen — check the "
                            f"wtf-ingest worker on boston-2."
                        ),
                        actions=["details", "snooze"],
                    )
                # Floor 30% catches total-breakage while the historical backlog drains
                # post-#2272; raise to ~70% once the settled cohort stabilises high.
                if (
                    _beat_cov is not None
                    and _beat_cov < 30.0
                    and now - self._watchdog_last_alert.get("wtf_beat_coverage", 0) > dedup_s
                ):
                    self._watchdog_last_alert["wtf_beat_coverage"] = now
                    from services.alert_actions_service import send_alert

                    send_alert(
                        alert_key="wtf_beat_coverage",
                        title="⚠️ WTF beat coverage low",
                        message=(
                            f"what-the-fact.com: only {_beat_cov:.0f}% of the settled "
                            f"(24-48h) article cohort has been beat-classified "
                            f"(floor 30%). The category tabs are starving — check the "
                            f"beat_backlog_worker on boston-2."
                        ),
                        actions=["details", "snooze"],
                    )
            except Exception as _we:
                logger.warning(f"watchdog wtf-ingest freshness check failed: {_we}")

            for category, msg in triggered:
                try:
                    # Interactive alert: 📊 Details + 🔕 Snooze 24h buttons (#alert-buttons).
                    # send_alert is snooze-gated + sends direct (buttons survive; the inbox
                    # relay strips reply_markup). `category` here is the alert_key (disk_primary…).
                    from services.alert_actions_service import send_alert

                    send_alert(
                        alert_key=category,
                        title=f"Platform Watchdog: {category.upper()} pressure",
                        message=f"{msg}\nload1={load1:.1f} mem_avail={mem_avail_gb:.1f}GB swap_free={swap_free_gb:.2f}GB",
                        actions=["details", "snooze"],
                    )
                except Exception as e:
                    logger.warning(f"watchdog telegram failed: {e}")

            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle(
                "platform_watchdog",
                len(triggered),
                0,
                duration_ms,
                details={
                    "load1": round(load1, 2),
                    "mem_avail_gb": round(mem_avail_gb, 2),
                    "swap_free_gb": round(swap_free_gb, 2),
                    "alerts_fired": [c for c, _ in triggered],
                },
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("platform_watchdog", 0, 1, duration_ms, error_message=str(e))

    def _comfyui_idle_stop(self):
        """Stop ComfyUI container after 30 min idle (Project #240 task #2019).

        Parallel to Ollama KEEP_ALIVE=5m. Keeps kernel from paging out
        ComfyUI's 165GB virtual alloc — that polluted swap with 6.5GB
        on 2026-04-16.
        """
        start = time.time()
        try:
            from services.comfyui_lifecycle import idle_stop_if_needed

            result = idle_stop_if_needed(max_idle_seconds=1800)
            duration_ms = int((time.time() - start) * 1000)
            items = 1 if result.get("action") == "stopped" else 0
            self._log_cycle("comfyui_idle_stop", items, 0, duration_ms, details=result)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("comfyui_idle_stop", 0, 1, duration_ms, error_message=str(e))

    def _media_queue_cleanup(self):
        """Media queue cleanup every 1h — migrated from app.py."""
        start = time.time()
        try:
            from tools.media_studio.services.batch_service import cleanup_stale_queue

            cleaned = cleanup_stale_queue(max_age_hours=24)
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("media_queue_cleanup", cleaned or 0, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("media_queue_cleanup", 0, 1, duration_ms, error_message=str(e))

    def _media_export_cleanup(self):
        """Media export cleanup every 1h — migrated from app.py."""
        start = time.time()
        try:
            from tools.media_studio.services.batch_service import cleanup_expired_exports

            cleaned = cleanup_expired_exports()
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("media_export_cleanup", cleaned or 0, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("media_export_cleanup", 0, 1, duration_ms, error_message=str(e))

    def _reap_stale_jobs(self):
        """Reap orphaned bridge jobs that stopped updating (every 2 min).

        8-min threshold (up from 5) gives outpost fleet agents headroom
        when the queue is momentarily deep (WTF burst — KB #267773).
        """
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            reaped = dispatcher.reap_stale_jobs(max_age_minutes=8)
            if reaped:
                logger.info(f"Stale job reaper: cleaned {reaped} orphaned jobs")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _reap_stuck_jobs(self):
        """Kill jobs stuck in 'running' state too long (every 5 min)."""
        try:
            from database import get_db_cursor
            from tools.security_network.security_alerts import create_security_alert

            with get_db_cursor(commit=True) as (conn, cur):
                # Jobs running > 30 minutes are stuck
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET status = 'failed',
                        error_message = 'Auto-killed: job exceeded 30 minute timeout',
                        completed_at = NOW()
                    WHERE status = 'running'
                      AND created_at < NOW() - INTERVAL '30 minutes'
                    RETURNING id, job_type, agent_name, module_source
                """
                )
                killed = cur.fetchall()

            for job in killed:
                logger.warning(f"Stuck job killed: #{job['id']} {job['job_type']} by {job['agent_name']}")
                try:
                    create_security_alert(
                        "scan_result",
                        f"Stuck job auto-killed: {job['job_type']}",
                        f"Job #{job['id']} by {job['agent_name']} in {job['module_source']} exceeded 30min timeout",
                        priority="normal",
                        telegram=False,
                    )
                except Exception:
                    pass

            if killed:
                logger.info(f"Stuck job watchdog: killed {len(killed)} hung jobs")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _run_qa_scheduled(self):
        """Run all active internal QA suites on schedule (every 6h).

        Per-suite results are recorded in details so the boot briefing can
        surface which suites failed without DB digging (PR #503).

        Path B (post PR #507): authenticate once per (base_url, username) pair
        and reuse the resulting requests.Session across every suite that
        matches. The platform runs gunicorn with --workers=1 (APScheduler is
        in-process and bumping workers double-fires jobs); under the bulk
        55-suite loop, repeated logins contended on that single worker and
        ~50% of suites failed at auth init in 10s. Sharing an authenticated
        session removes the contention without touching gunicorn config.
        """
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            import requests as http_requests
            from services import qa_service
            from services.qa_spec_runner import _authenticate, _resolve_env_vars
            from database import get_db_cursor

            # Health gate — skip the run entirely if the platform is mid-restart.
            # Restarts take <30s; a 6h window means skipping one cycle on the rare
            # occasion the scheduler fires during a bounce is the right trade-off
            # over producing 65 false failure records.
            _platform_url = os.environ.get("PLATFORM_URL", "http://192.168.1.200:3000")
            try:
                _health = http_requests.get(f"{_platform_url}/api/health", timeout=10, allow_redirects=False)
                if _health.status_code != 200:
                    logger.warning(
                        "QA scheduled run skipped — platform health check returned %s "
                        "(likely mid-restart). Will retry at next 6h interval.",
                        _health.status_code,
                    )
                    return
            except Exception as _health_err:
                logger.warning(
                    "QA scheduled run skipped — platform unreachable: %s "
                    "(likely mid-restart). Will retry at next 6h interval.",
                    _health_err,
                )
                return

            start = time.time()
            suites = qa_service.get_suites()
            internal_suites = [s for s in suites if s.get("suite_type") == "internal"]

            # qa_service.get_suites() omits the spec column — fetch it once
            # for every internal suite so we can group by (base_url, auth).
            specs_by_id = {}
            if internal_suites:
                ids = tuple(s["id"] for s in internal_suites)
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT id, spec FROM qa_test_suites WHERE id = ANY(%s)",
                        (list(ids),),
                    )
                    for row in cur.fetchall():
                        specs_by_id[row["id"]] = row["spec"] or {}

            total_passed = 0
            total_failed = 0
            per_suite = []
            shared_session = None
            shared_key = None  # (base_url, username) — password compared too but excluded from logs
            shared_password = None
            session_reuse_count = 0

            for suite in internal_suites:
                spec_data = specs_by_id.get(suite["id"], {}) or {}
                spec_resolved = _resolve_env_vars(spec_data)
                suite_meta = spec_resolved.get("suite", {}) if isinstance(spec_resolved, dict) else {}
                base_url = (
                    suite_meta.get("base_url") or os.environ.get("PLATFORM_URL", "http://localhost:3000")
                ).rstrip("/")
                auth = suite_meta.get("auth") or {}
                has_auth = bool(auth.get("username") and auth.get("password"))

                use_shared = False
                if has_auth:
                    key = (base_url, auth["username"])
                    if shared_key == key and shared_password == auth["password"] and shared_session is not None:
                        use_shared = True
                    else:
                        # New auth pair — build a fresh session and pre-auth once
                        try:
                            fresh = http_requests.Session()
                            _authenticate(fresh, base_url, auth)
                            shared_session = fresh
                            shared_key = key
                            shared_password = auth["password"]
                            use_shared = True
                            session_reuse_count = 0
                            logger.info(
                                "QA scheduled: pre-authenticated shared session for %s as %s",
                                base_url,
                                auth["username"],
                            )
                        except Exception as auth_err:
                            logger.warning(
                                "QA scheduled: shared session pre-auth failed for %s as %s — "
                                "falling back to per-suite auth: %s",
                                base_url,
                                auth["username"],
                                auth_err,
                            )
                            shared_session = None
                            shared_key = None
                            shared_password = None
                            use_shared = False

                if use_shared:
                    session_reuse_count += 1

                result = qa_service.run_suite(
                    suite["id"],
                    triggered_by="scheduled",
                    session=(shared_session if use_shared else None),
                    skip_auth=use_shared,
                )
                p = result.get("passed", 0)
                f = result.get("failed", 0)
                e = result.get("errors", 0)
                total_passed += p
                total_failed += f + e
                per_suite.append(
                    {
                        "suite_id": suite["id"],
                        "name": suite.get("name", "?"),
                        "passed": p,
                        "failed": f,
                        "errors": e,
                        "shared_session": use_shared,
                    }
                )
                # Sharing a session eliminates the per-suite auth round-trip
                # that was contending on the single gunicorn worker, so 2s
                # between suites is enough to keep request volume civil.
                time.sleep(2)

            duration_ms = int((time.time() - start) * 1000)
            failing = [s for s in per_suite if s["failed"] > 0 or s["errors"] > 0]
            self._log_cycle(
                "qa_scheduled",
                total_passed,
                total_failed,
                duration_ms,
                details={
                    "per_suite": per_suite,
                    "failing_suite_count": len(failing),
                    "failing_suites": [s["name"] for s in failing],
                    "shared_session_suites": sum(1 for s in per_suite if s.get("shared_session")),
                },
            )
        except Exception as e:
            logger.warning(f"QA scheduled run failed: {e}")

    # ------------------------------------------------------------------
    # W.A.R.D.E.N. admin ops jobs (agent #363, Operations & Infrastructure)
    # ------------------------------------------------------------------

    def _run_warden_user_audit(self):
        """Daily user account audit — inactive users, locked accounts, expired invites."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            # #5340: queue-aware dispatch (ADR-990 / KB #276153). The bare dispatch()
            # held a 240s sync window that a qwen2.5:7b cold-load blows (~30% of daily
            # runs), and the resulting retries tripped the hub 7B admission cap. The
            # queued path rides dispatch_pending_queue instead: the row waits for
            # warmth and the worker delivers whenever the model lands. Daily job —
            # latency is irrelevant, completion is everything, so the poll window is
            # generous (queue-row expiry still bounds it).
            from services.cluster_dispatch import queued_dispatch_text

            start = time.time()
            text = queued_dispatch_text(
                "user_audit",
                (
                    "Run a daily user account audit for the A.R.C.H.I.E. platform. "
                    "Check for: (1) users inactive for more than 30 days, "
                    "(2) currently locked accounts (auth_events), "
                    "(3) expired or pending invites older than 7 days. "
                    "Summarise findings concisely. Flag anything that needs attention."
                ),
                module_id="warden_daily",
                poll_timeout_s=900,
            )
            duration_ms = int((time.time() - start) * 1000)
            success = bool(text)
            self._log_cycle(
                "warden_user_audit",
                1 if success else 0,
                0 if success else 1,
                duration_ms,
                details={"response": text[:500] if text else "no response"},
            )
        except Exception as e:
            logger.error("warden_user_audit failed: %s", e)

    def _run_warden_backup_verify(self):
        """Daily backup integrity check — checksums, age, retention policy."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from database import get_db_cursor

            start = time.time()

            # DETERMINISTIC CHECK + ALERT FIRST — this must not depend on the LLM below.
            # This job used to query `FROM backups`, a table that DOES NOT EXIST (it is
            # `backup_log`), so every run threw and the except swallowed it; and even on
            # success it had no alert path — the model's "flag anything" answer went into a
            # log row nobody reads. Backups were therefore unmonitored while appearing
            # monitored. See services/backup_posture_monitor.py and task #5014.
            try:
                from services.backup_posture_monitor import check_backup_posture

                posture = check_backup_posture()
                if posture.get("alerted"):
                    logger.warning("warden_backup_verify: posture alerts %s", posture["alerted"])
            except Exception as _pe:
                logger.error("warden_backup_verify: posture check failed: %s", _pe)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT backup_type, status, created_at, size_bytes, tier
                       FROM backup_log ORDER BY created_at DESC LIMIT 10"""
                )
                recent = cur.fetchall()

            summary = (
                ", ".join(
                    f"{r['backup_type'] or r['tier'] or 'backup'}"
                    f"({r['status']}, {r['created_at'].strftime('%Y-%m-%d')})"
                    for r in (recent or [])
                )
                or "no backups found"
            )

            # #5340: queue-aware LLM leg — see _run_warden_user_audit. The
            # deterministic posture check + backup_log query above are unaffected.
            from services.cluster_dispatch import queued_dispatch_text

            text = queued_dispatch_text(
                "backup_verify",
                (
                    f"Verify backup health. Recent backups: {summary}. "
                    "Check: (1) is the most recent DB backup less than 24h old? "
                    "(2) are any backups in failed/error status? "
                    "(3) is retention policy being followed (7 daily, 4 weekly)? "
                    "Flag anything that needs attention."
                ),
                module_id="warden_daily",
                poll_timeout_s=900,
            )
            duration_ms = int((time.time() - start) * 1000)
            success = bool(text)
            self._log_cycle(
                "warden_backup_verify",
                1 if success else 0,
                0 if success else 1,
                duration_ms,
                details={"response": text[:500] if text else "no response"},
            )
        except Exception as e:
            logger.error("warden_backup_verify failed: %s", e)

    def _run_warden_compliance_check(self):
        """Weekly compliance scan across all 4 admin modules.

        Queue-tolerant (#4151): a cold-model dispatch returns queued=True — the task
        is deferred to dispatch_pending_queue and the model_dispatch_worker finishes
        it moments later — rather than a finished result. We poll that row to its
        terminal state instead of treating 'queued' as an instant failure, and we
        record the real reason on failure (previously swallowed → error_message NULL).
        Decision logic is the pure services.dispatch_cycle.classify_dispatch_cycle."""
        start = time.time()
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.department_hq.services.department_dispatcher import dispatch
            from services.dispatch_cycle import classify_dispatch_cycle

            result = dispatch(
                capability="compliance_check",
                prompt=(
                    "Run a weekly compliance review for the 4 admin operations modules: "
                    "account_center, security_network, backup_manager, system_operations. "
                    "Check: (1) code health status in code_audit_log, "
                    "(2) any new open improvement_proposals in the last 7 days, "
                    "(3) QA suite pass rates from qa_suite_runs in the last 7 days. "
                    "Produce a concise weekly admin health report."
                ),
            )
            queue_final = None
            if result is not None and getattr(result, "queued", False) and getattr(result, "queue_id", None):
                queue_final = self._poll_pending_queue(result.queue_id)
            outcome = classify_dispatch_cycle(result, queue_final)
            self._log_cycle(
                "warden_compliance_check",
                outcome.items_processed,
                outcome.items_failed,
                int((time.time() - start) * 1000),
                details={"response": outcome.response or "no response"},
                error_message=outcome.error_message,
            )
        except Exception as e:
            logger.error("warden_compliance_check failed: %s", e)
            self._log_cycle(
                "warden_compliance_check",
                0,
                1,
                int((time.time() - start) * 1000),
                details={"response": "exception"},
                error_message=f"exception: {e}",
            )

    def _poll_pending_queue(self, queue_id, timeout_s=600, interval_s=15):
        """Poll a dispatch_pending_queue row until it reaches a terminal state
        (done/failed/expired) or timeout. Returns {'status','result_response','error'}
        for the terminal row, or None if still non-terminal at timeout (the caller
        treats None as in-progress, NOT a failure). Read-only; never raises.

        Used by queue-tolerant single-dispatch jobs (compliance_check) so a cold 7B
        model that defers to the queue is awaited rather than mis-logged as failed.
        Reads through the service layer that owns dispatch_pending_queue (no raw SQL
        in the job)."""
        try:
            from services.model_dispatch_service import get_pending_queue_result
        except Exception as e:
            logger.warning("warden_compliance_check poll: queue reader unavailable: %s", e)
            return None
        # Terminal states mirror services.dispatch_cycle.QUEUE_TERMINAL_STATES.
        terminal = ("done", "failed", "expired")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            row = None
            try:
                row = get_pending_queue_result(queue_id)
            except Exception as e:
                logger.warning("warden_compliance_check poll: queue read failed for #%s: %s", queue_id, e)
            if row is not None:
                status = (row.get("status") or "").lower()
                if status in terminal:
                    return {
                        "status": status,
                        "result_response": row.get("result_response"),
                        "error": row.get("error"),
                    }
            time.sleep(interval_s)
        return None

    def _run_warden_wtf_rsync(self):
        """Every 15 min: if WTF git HEAD changed, rsync hub→VPS (code-only, no container restart).
        Requires SSH key mounted at /root/.ssh/id_ed25519 inside archie_platform container.
        On SSH key missing: logs a warning and skips — degraded gracefully."""
        try:
            import os
            import subprocess
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from database import get_db_cursor

            WTF_LOCAL = "/mnt/archie_brain/what-the-fact"
            WTF_VPS = "kytran@76.13.107.109:/opt/archie-products/what-the-fact/"
            SSH_KEY = "/root/.ssh/id_ed25519"

            # 1. Get current git HEAD SHA for the WTF directory
            # Run git from the repo root (/mnt/archie_brain) to avoid filesystem
            # boundary issue — WTF_LOCAL is a bind-mount subdirectory and git
            # refuses to cross mount points to find .git by default.
            # Using `git log -- what-the-fact/` gives the last commit touching WTF
            # files, which is semantically correct (only rsync when WTF changes).
            # Pass safe.directory via env so git doesn't reject the bind-mounted
            # repo (owned by kytran on host, container runs as root — git 2.35.2+
            # "dubious ownership" check blocks access without this override).
            _git_env = {
                **os.environ,
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": "/mnt/archie_brain",
            }
            git_result = subprocess.run(
                ["git", "log", "--format=%H", "-1", "--", "what-the-fact/"],
                cwd="/mnt/archie_brain",
                capture_output=True,
                text=True,
                timeout=10,
                env=_git_env,
            )
            if git_result.returncode != 0 or not git_result.stdout.strip():
                logger.warning(
                    "warden_wtf_rsync: git log failed — %s",
                    git_result.stderr.strip()[:200] or "no commits found for what-the-fact/",
                )
                return
            current_sha = git_result.stdout.strip()

            # 2. Compare against last synced SHA stored in system_config
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT value FROM system_config WHERE key = 'wtf_last_rsync_sha'")
                row = cur.fetchone()
            last_sha = row["value"] if row else None

            if current_sha == last_sha:
                logger.debug("warden_wtf_rsync: no change since last sync (%s)", current_sha[:8])
                return

            # 3. SSH key must be accessible from inside the container
            if not os.path.exists(SSH_KEY):
                logger.warning(
                    "warden_wtf_rsync: SSH key not found at %s — "
                    "mount ~/.ssh into archie_platform container or run "
                    "cd /mnt/archie_brain/what-the-fact && ./deploy.sh manually. "
                    "Pending SHA: %s",
                    SSH_KEY,
                    current_sha[:8],
                )
                return

            # 4. Rsync code to VPS (excludes .env so live secrets are preserved)
            start = time.time()
            rsync_result = subprocess.run(
                [
                    "rsync",
                    "-az",
                    "--delete",
                    "--exclude=.env",
                    "--exclude=__pycache__",
                    "--exclude=*.pyc",
                    "--exclude=.git",
                    "--exclude=*.log",
                    "-e",
                    f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no",
                    f"{WTF_LOCAL}/",
                    WTF_VPS,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            duration_ms = int((time.time() - start) * 1000)

            if rsync_result.returncode != 0:
                logger.error(
                    "warden_wtf_rsync: rsync failed (SHA %s): %s",
                    current_sha[:8],
                    rsync_result.stderr.strip()[:300],
                )
                self._log_cycle(
                    "warden_wtf_rsync",
                    0,
                    1,
                    duration_ms,
                    details={
                        "sha": current_sha[:8],
                        "error": rsync_result.stderr.strip()[:300],
                    },
                )
                return

            # 5. Persist the new synced SHA so next tick skips if no change
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at)
                       VALUES ('wtf_last_rsync_sha', %s, NOW())
                       ON CONFLICT (key) DO UPDATE
                       SET value = EXCLUDED.value, updated_at = NOW()""",
                    (current_sha,),
                )

            logger.info(
                "warden_wtf_rsync: synced %s→%s to VPS in %dms",
                (last_sha or "init")[:8],
                current_sha[:8],
                duration_ms,
            )
            self._log_cycle(
                "warden_wtf_rsync",
                1,
                0,
                duration_ms,
                details={
                    "prev_sha": (last_sha or "")[:8],
                    "new_sha": current_sha[:8],
                },
            )
        except Exception as e:
            logger.error("warden_wtf_rsync failed: %s", e)

    def _archive_stale_notifications(self):
        """Archive notifications older than 30 days (every 6 hours)."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE system_notifications
                    SET is_archived = TRUE
                    WHERE is_archived = FALSE
                      AND created_at < NOW() - INTERVAL '30 days'
                    """
                )
                archived = cur.rowcount
            if archived:
                logger.info(f"Notification archiver: archived {archived} stale notifications")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _discover_network_devices(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py discover_network_devices()"""
        pass

    def _track_agent_hr(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py track_agent_hr()
        Aggregate task_execution_log into agent_daily_summary.
        Check for overwork, high error rates, and idle agents.
        Create alerts and send Telegram notifications for critical issues.
        Runs every 5 minutes.
        """
        pass

    def _recover_idle_welfare(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py recover_idle_welfare()
        Recover welfare for idle and resting agents.
        Runs every 30 minutes.
        - Idle (not dispatched in last hour): stress -0.15, energy +0.2
        - Resting (active rest cycle): stress -0.3, energy +0.4
        """
        pass

    def _volunteer_idle_agents(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py volunteer_idle_agents()
        Scan for idle agents and volunteer them at departments with pending work.
        Runs every 5 minutes.
        - Find departments with recent task failures
        - Find idle agents not in those departments
        - Create notifications for volunteering events
        """
        pass

    def _update_performance_rankings(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py update_performance_rankings()
        Calculate comparative performance rankings per capability.
        Runs every 15 minutes.
        rank_score = (success_rate * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)
        Minimum 10 tasks for reliable ranking — below that, blend static proficiency.
        """
        pass

    def _check_proficiency_degradation(self, cur, conn):
        """Check for agents with high failure rates and degrade their proficiency.

        Closed loop: dispatch → fail → degrade → train (personalized) → complete → restore.
        Returns count of degradations triggered.
        """
        degraded = 0
        try:
            # Load config thresholds
            cur.execute(
                "SELECT config_key, config_value FROM autonomy_config "
                "WHERE config_key IN ('training_failure_threshold', 'training_min_tasks', "
                "'training_lookback_days', 'training_hours_per_level')"
            )
            cfg = {}
            for row in cur.fetchall():
                val = row["config_value"]
                cfg[row["config_key"]] = val if isinstance(val, str) else json.dumps(val)

            failure_threshold = int(cfg.get("training_failure_threshold", "50"))
            min_tasks = int(cfg.get("training_min_tasks", "5"))
            lookback_days = int(cfg.get("training_lookback_days", "7"))
            try:
                hours_per_level = json.loads(cfg.get("training_hours_per_level", '{"2":1,"3":2,"4":4,"5":8}'))
            except (json.JSONDecodeError, TypeError):
                hours_per_level = {"2": 1, "3": 2, "4": 4, "5": 8}

            # Find agents with high failure rates per capability
            cur.execute(
                """
                SELECT tel.agent_id, tel.capability,
                       COUNT(*) as total,
                       SUM(CASE WHEN tel.success = FALSE THEN 1 ELSE 0 END) as failures,
                       a.name as agent_name,
                       COALESCE(a.display_name, a.first_name || ' ' || a.last_name) as display_name
                FROM task_execution_log tel
                JOIN agents a ON a.id = tel.agent_id
                WHERE tel.created_at > NOW() - INTERVAL '1 day' * %s
                  AND tel.agent_id IS NOT NULL
                  AND tel.capability IS NOT NULL
                GROUP BY tel.agent_id, tel.capability, a.name, a.display_name, a.first_name, a.last_name
                HAVING COUNT(*) >= %s
            """,
                (lookback_days, min_tasks),
            )
            candidates = cur.fetchall()

            for row in candidates:
                failure_rate = round((row["failures"] / row["total"]) * 100, 1)
                if failure_rate < failure_threshold:
                    continue

                agent_id = row["agent_id"]
                capability = row["capability"]
                agent_name = row["agent_name"]
                display_name = row["display_name"] or agent_name

                # Get current proficiency from agent_learning_log
                cur.execute(
                    """
                    SELECT id, confidence, last_degraded_at
                    FROM agent_learning_log
                    WHERE agent_id = %s AND skill_name = %s
                    ORDER BY confidence DESC LIMIT 1
                """,
                    (agent_id, capability),
                )
                skill_row = cur.fetchone()

                if not skill_row:
                    continue

                confidence = float(skill_row["confidence"])
                # Map confidence to level: <0.3=1, <0.5=2, <0.7=3, <0.85=4, >=0.85=5
                if confidence < 0.3:
                    current_level = 1
                elif confidence < 0.5:
                    current_level = 2
                elif confidence < 0.7:
                    current_level = 3
                elif confidence < 0.85:
                    current_level = 4
                else:
                    current_level = 5

                # Guard: skip if already at Lv1
                if current_level <= 1:
                    continue

                # Guard: skip if degraded within last 24 hours
                if skill_row["last_degraded_at"]:
                    from datetime import timezone

                    last_degraded = skill_row["last_degraded_at"]
                    if hasattr(last_degraded, "tzinfo") and last_degraded.tzinfo is None:
                        last_degraded = last_degraded.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
                    if (now_utc - last_degraded).total_seconds() < 86400:
                        continue

                # Guard: skip if already in training for this skill
                cur.execute(
                    """
                    SELECT id FROM training_assignments
                    WHERE agent_id = %s AND skill_name = %s AND status IN ('pending', 'in_progress')
                    LIMIT 1
                """,
                    (agent_id, capability),
                )
                if cur.fetchone():
                    continue

                # Degrade: reduce confidence by 0.2
                new_confidence = max(0.1, confidence - 0.2)
                cur.execute(
                    """
                    UPDATE agent_learning_log
                    SET confidence = %s, last_degraded_at = NOW(),
                        degradation_count = COALESCE(degradation_count, 0) + 1
                    WHERE id = %s
                """,
                    (round(new_confidence, 2), skill_row["id"]),
                )

                # Recalculate level after degradation
                if new_confidence < 0.3:
                    new_level = 1
                elif new_confidence < 0.5:
                    new_level = 2
                elif new_confidence < 0.7:
                    new_level = 3
                elif new_confidence < 0.85:
                    new_level = 4
                else:
                    new_level = 5

                # Generate failure analysis via local LLM
                failure_analysis = None
                failure_summary = {
                    "capabilities": [capability],
                    "task_count": row["total"],
                    "failure_rate": failure_rate,
                    "error_patterns": [],
                }
                try:
                    cur.execute(
                        """
                        SELECT capability, error_message, module_source
                        FROM task_execution_log
                        WHERE agent_id = %s AND capability = %s AND success = FALSE
                          AND created_at > NOW() - INTERVAL '1 day' * %s
                        ORDER BY created_at DESC LIMIT 10
                    """,
                        (agent_id, capability, lookback_days),
                    )
                    recent_errors = cur.fetchall()

                    error_texts = []
                    for err in recent_errors:
                        msg = err.get("error_message") or "No error message"
                        mod = err.get("module_source") or "unknown"
                        error_texts.append(f"- [{mod}] {msg[:200]}")
                        if msg not in failure_summary["error_patterns"]:
                            failure_summary["error_patterns"].append(msg[:100])

                    if error_texts:
                        from tools.department_hq.services.department_dispatcher import get_dispatcher

                        disp = get_dispatcher()
                        if disp:
                            prompt = (
                                f"Agent '{display_name}' failed {failure_rate}% of '{capability}' tasks "
                                f"({row['failures']}/{row['total']} in {lookback_days} days).\n\n"
                                f"Recent errors:\n" + "\n".join(error_texts[:10]) + "\n\n"
                                "What specific patterns are causing failures? "
                                "Give 2-3 actionable corrections the agent should apply."
                            )
                            result = disp.request_work(
                                capability="summarize",
                                prompt=prompt,
                                module_id="training_system",
                            )
                            if result and result.success:
                                failure_analysis = (result.response or "")[:2000]
                except Exception as e:
                    logger.warning(f"Failed to generate failure analysis for {agent_name}/{capability}: {e}")

                # Calculate training duration from hours_per_level
                target_level = current_level  # Restore to pre-degradation level
                hours_key = str(target_level)
                training_hours = int(hours_per_level.get(hours_key, hours_per_level.get(str(2), 2)))

                # Create training assignment
                cur.execute(
                    """
                    INSERT INTO training_assignments
                    (agent_id, skill_name, target_proficiency, current_proficiency,
                     status, started_at, target_completion,
                     failure_analysis, degradation_triggered, failure_summary)
                    VALUES (%s, %s, %s, %s, 'in_progress', NOW(), NOW() + INTERVAL '1 hour' * %s,
                            %s, TRUE, %s)
                """,
                    (
                        agent_id,
                        capability,
                        target_level,
                        new_level,
                        training_hours,
                        failure_analysis,
                        json.dumps(failure_summary),
                    ),
                )

                # Create HR alert
                self._create_hr_alert(
                    cur,
                    agent_id,
                    "proficiency_degradation",
                    "warning",
                    f"{display_name}: degraded to Lv{new_level} on {capability}",
                    f"Agent {display_name} dropped from Lv{current_level} to Lv{new_level} "
                    f"on {capability} ({failure_rate}% failure rate over {row['total']} tasks). "
                    f"Auto-training started ({training_hours}h).",
                    {
                        "capability": capability,
                        "failure_rate": failure_rate,
                        "old_level": current_level,
                        "new_level": new_level,
                        "training_hours": training_hours,
                    },
                )

                degraded += 1
                logger.info(
                    f"Proficiency degradation: {display_name} Lv{current_level}→Lv{new_level} "
                    f"on {capability} ({failure_rate}% failures). Training: {training_hours}h"
                )

            if degraded > 0:
                conn.commit()

        except Exception as e:
            logger.error(f"Proficiency degradation check failed: {e}")

        return degraded

    def _process_training_tick(self):
        """DEPRECATED (Phase 5): Moved to services/agent_jobs.py process_training_tick()
        Check for completed training assignments and finalize them.

        When target_completion is reached:
        - Mark training as completed
        - Restore/boost confidence in agent_learning_log
        - Store failure_analysis as knowledge_base entry
        - Nudge emotional state positively
        - Send Telegram notification
        """
        pass

    def _create_hr_alert(self, cur, agent_id, alert_type, severity, title, message, details=None):
        """Create an HR alert with deduplication (same type+agent within 1 hour)."""
        try:
            cur.execute(
                """
                SELECT id FROM agent_alerts
                WHERE agent_id = %s AND alert_type = %s AND resolved = FALSE
                  AND created_at > NOW() - INTERVAL '1 hour'
                LIMIT 1
            """,
                (agent_id, alert_type),
            )
            if cur.fetchone():
                return 0  # Already alerted recently

            cur.execute(
                """
                INSERT INTO agent_alerts
                (agent_id, alert_type, severity, title, message, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (agent_id, alert_type, severity, title, message, json.dumps(details or {})),
            )

            # Log governance event for critical alerts
            if severity == "critical":
                log_governance_event(
                    "agent_welfare",
                    f"alert_{alert_type}",
                    "alert_created",
                    {"agent_id": agent_id, "title": title},
                )

            return 1
        except Exception as e:
            logger.error(f"Failed to create HR alert: {e}")
            return 0

    def _send_hr_telegram_alerts(self, cur, conn):
        """Send unnotified critical/warning alerts via Telegram."""
        try:
            import asyncio

            # Find the running gateway instance
            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if not gateway or not gateway.is_running:
                return

            # Get unnotified alerts
            cur.execute(
                """
                SELECT aa.id, aa.agent_id, aa.alert_type, aa.severity,
                       aa.title, aa.message, a.name as agent_name
                FROM agent_alerts aa
                LEFT JOIN agents a ON a.id = aa.agent_id
                WHERE aa.notified_telegram = FALSE
                  AND aa.severity IN ('critical', 'warning')
                ORDER BY
                    CASE aa.severity WHEN 'critical' THEN 1 ELSE 2 END,
                    aa.created_at ASC
                LIMIT 5
            """
            )
            alerts = cur.fetchall()
            if not alerts:
                return

            # Get authorized Telegram user
            cur.execute(
                """
                SELECT telegram_id FROM telegram_users
                WHERE is_authorized = TRUE AND user_id IS NOT NULL
                LIMIT 1
            """
            )
            tg_user = cur.fetchone()
            if not tg_user:
                return

            telegram_id = tg_user["telegram_id"]
            loop = gateway._loop

            for alert in alerts:
                severity_icon = "\u26a0\ufe0f" if alert["severity"] == "warning" else "\U0001f6a8"
                text = (
                    f"{severity_icon} *HR Alert: {alert['title']}*\n\n"
                    f"{alert['message']}\n\n"
                    f"_Type: {alert['alert_type']} | Agent: {alert['agent_name'] or 'System'}_"
                )

                try:
                    asyncio.run_coroutine_threadsafe(
                        gateway._application.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                            parse_mode="Markdown",
                        ),
                        loop,
                    )

                    cur.execute(
                        "UPDATE agent_alerts SET notified_telegram = TRUE WHERE id = %s",
                        (alert["id"],),
                    )
                except Exception as e:
                    logger.error(f"Failed to send HR alert to Telegram: {e}")

            conn.commit()

        except ImportError:
            pass  # Telegram not available
        except Exception as e:
            logger.error(f"HR Telegram alerts failed: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_enabled(self, cur, config_key: str) -> bool:
        """Check if a feature is enabled in autonomy_config."""
        try:
            cur.execute(
                "SELECT config_value FROM autonomy_config WHERE config_key = %s",
                (config_key,),
            )
            row = cur.fetchone()
            if not row:
                return True  # Default to enabled if no config
            return row["config_value"].get("enabled", True)
        except Exception:
            return True

    def _get_config(self, cur, config_key: str) -> dict:
        """Get configuration for a feature."""
        try:
            cur.execute(
                "SELECT config_value FROM autonomy_config WHERE config_key = %s",
                (config_key,),
            )
            row = cur.fetchone()
            return row["config_value"] if row else {}
        except Exception:
            return {}

    def _create_notification(
        self,
        cur,
        notification_type: str,
        title: str,
        message: str,
        source: str,
        priority: str = "normal",
        related_action: str = None,
        visibility: str = "all",
        target_user_id: int = None,
    ):
        """Create a system notification with deduplication."""
        # Deduplication: check for same message in last 5 minutes
        dedup_sql = """
            SELECT id, grouped_count FROM system_notifications
            WHERE message = %s AND type = %s AND source = %s
              AND created_at > NOW() - INTERVAL '5 minutes'
              AND is_read = FALSE
        """
        dedup_params = [message, notification_type, source]
        if target_user_id is not None:
            dedup_sql += " AND target_user_id = %s"
            dedup_params.append(target_user_id)
        else:
            dedup_sql += " AND target_user_id IS NULL"
        dedup_sql += " ORDER BY created_at DESC LIMIT 1"
        cur.execute(dedup_sql, dedup_params)
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE system_notifications
                SET grouped_count = grouped_count + 1, created_at = NOW()
                WHERE id = %s
                """,
                (existing["id"],),
            )
        else:
            cur.execute(
                """
                INSERT INTO system_notifications
                (type, title, message, source, priority, source_icon, related_action,
                 visibility, target_user_id, is_read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW())
                """,
                (
                    notification_type,
                    title,
                    message,
                    source,
                    priority,
                    "bot",
                    related_action,
                    visibility,
                    target_user_id,
                ),
            )

    def _log_cycle(
        self,
        job_name: str,
        items_processed: int,
        items_failed: int,
        duration_ms: int,
        details: dict = None,
        error_message: str = None,
    ):
        """Log an agent loop execution cycle."""
        status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
        # #5339: 107 of 107 failing rows recorded NO reason. Resolve it here rather
        # than at 186 call sites — most are inside an `except`, so the exception is
        # still live in sys.exc_info(). An explicit caller message always wins.
        #
        # GUARDED because this runs on the LOGGING path of every job. Not every caller
        # reaches _log_cycle with platform_v2 on sys.path — fleet_jobs inserts it
        # explicitly before its own service imports — and an ImportError here would
        # turn a LOGGED failure into an UNLOGGED crash, strictly worse than the bug
        # being fixed. F.O.R.G.E. flagged exactly this on PR #2546 and was right.
        try:
            from services.loop_log import explain_failure

            error_message = explain_failure(status, items_failed, error_message, details)
        except Exception:  # noqa: BLE001 — the resolver must never break logging
            pass
        try:
            from tools.department_hq.services.job_registry import get_department_for_job

            department = get_department_for_job(job_name)
            if department == "UNKNOWN":
                # Fall back to legacy inline map during transition
                department = JOB_DEPARTMENT_MAP.get(job_name, "UNKNOWN")
        except Exception:
            department = JOB_DEPARTMENT_MAP.get(job_name, "UNKNOWN")
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO autonomy_loop_log
                (job_name, status, items_processed, items_failed, duration_ms, details, error_message, department)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job_name,
                    status,
                    items_processed,
                    items_failed,
                    duration_ms,
                    json.dumps(details or {}),
                    error_message,
                    department,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log agent cycle '{job_name}': {e}")

    def _log_autonomy_action(self, action_type: str, details: dict = None, success: bool = True):
        """Log an autonomous action to governance audit log."""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, outcome, details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    "autonomy_action",
                    "autonomous_operations",
                    None,
                    action_type,
                    "success" if success else "failure",
                    json.dumps(details or {}),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log autonomy action '{action_type}': {e}")

    def _process_world_events(self):
        try:
            from tools.game_studio.world_engine import process_pending_events

            count = process_pending_events()
            if count > 0:
                logger.info(f"[World Engine] Processed {count} events")
        except Exception as e:
            logger.error(f"[World Engine] Error: {e}")

    def _update_market_prices(self):
        try:
            from tools.game_studio.market_service import update_market_prices

            update_market_prices()
        except Exception as e:
            logger.error(f"[Market] Price update error: {e}")

    def _monitor_ssh_logins(self):
        """Monitor SSH auth log for failed/suspicious logins (every 5 min)."""
        import re
        import subprocess

        try:
            result = subprocess.run(
                ["journalctl", "-u", "ssh", "--since", "5 minutes ago", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0 or not result.stdout.strip():
                return

            from tools.security_network.security_alerts import create_security_alert

            lines = result.stdout.strip().split("\n")
            failed_by_ip = {}
            root_attempts = []
            external_logins = []

            for line in lines:
                # Failed password attempts
                failed_match = re.search(r"Failed password for (?:invalid user )?(\S+) from (\S+)", line)
                if failed_match:
                    user = failed_match.group(1)
                    ip = failed_match.group(2)
                    failed_by_ip[ip] = failed_by_ip.get(ip, 0) + 1
                    if user == "root":
                        root_attempts.append(ip)
                    continue

                # Successful logins (Accepted)
                accepted_match = re.search(r"Accepted \S+ for (\S+) from (\S+)", line)
                if accepted_match:
                    user = accepted_match.group(1)
                    ip = accepted_match.group(2)
                    # External = not local network
                    if not ip.startswith("192.168.1."):
                        external_logins.append((user, ip))
                    if user == "root":
                        root_attempts.append(ip)

            alerts_created = 0

            # Brute force: 3+ failed from same IP
            for ip, count in failed_by_ip.items():
                if count >= 3:
                    create_security_alert(
                        "intrusion",
                        f"SSH brute force attempt from {ip}",
                        f"{count} failed login attempts from {ip} in the last 5 minutes",
                        priority="high",
                        telegram=True,
                    )
                    alerts_created += 1

            # External successful logins
            for user, ip in external_logins:
                create_security_alert(
                    "intrusion",
                    f"External SSH login from {ip}",
                    f"User '{user}' logged in via SSH from external IP {ip}",
                    priority="critical",
                    telegram=True,
                )
                alerts_created += 1

            # Root login attempts (deduplicate IPs already covered by brute force)
            seen_root_ips = set()
            for ip in root_attempts:
                if ip not in seen_root_ips:
                    seen_root_ips.add(ip)
                    create_security_alert(
                        "intrusion",
                        f"Root SSH login attempt from {ip}",
                        f"Someone attempted to log in as root via SSH from {ip}",
                        priority="normal",
                        telegram=True,
                    )
                    alerts_created += 1

            if alerts_created:
                logger.info(f"SSH monitor: created {alerts_created} security alerts")

        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _check_mission_schedule(self):
        """Check and apply scheduled mission profile changes (every 5 min)."""
        try:
            from ai_bridge.mission_manager import MissionManager

            mm = MissionManager()
            mm.check_schedule()
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _run_security_audit(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py run_security_audit()"""
        pass

    def _run_scheduled_compliance_scan(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py run_scheduled_compliance_scan()"""
        pass

    def _run_auto_remediation(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py run_auto_remediation()"""
        pass

    def _check_ssl_expiry(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py check_ssl_expiry()"""
        pass

    def _daily_dns_report(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py daily_dns_report()"""
        pass

    def _detect_query_spike(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py detect_query_spike()"""
        pass

    def _check_camera_anomaly(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py check_camera_anomaly()"""
        pass

    def _run_auto_block(self):
        """DEPRECATED (Phase 5): Moved to security_network/jobs.py run_auto_block()"""
        pass

    def _daily_code_metrics_scan(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py daily_code_metrics_scan()
        Job #40: Daily codebase metrics snapshot at 3:00 AM with stale audit detection."""
        pass

    def _pattern_compliance_check(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py pattern_compliance_check()
        Job #41: Scan for pattern violations at 4:00 AM."""
        pass

    def _automated_module_audit(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py automated_module_audit()
        Job #58: Automated module audit — weekly Sunday 3:30 AM."""
        pass

    def _daily_code_health_digest(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py daily_code_health_digest()
        Job #51: Send a morning Telegram summary of code health status at 8:00 AM."""
        pass

    def _daily_code_health_scan(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py daily_code_health_scan()
        Job #55: Run codebase scan daily at 2:00 AM. Saves snapshot for Code Health tab."""
        pass

    def _competitor_landscape_scan(self):
        """DEPRECATED (Phase 5): Moved to dev_hq/jobs.py competitor_landscape_scan()
        Job #52: Scan AI competitor landscape every 2 weeks, update knowledge_base, notify via Telegram."""
        pass

    def _sync_learned_skills(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py sync_learned_skills()"""
        pass

    def _github_auto_pull(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py github_auto_pull()"""
        pass

    def _analyze_discovered_skills(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py analyze_discovered_skills()"""
        pass

    def _check_fleet_health(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py check_fleet_health()
        Job #45: Monitor fleet node heartbeats — return agents to barracks if offline."""
        pass

    def _check_mesh_health(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py check_mesh_health()
        Job #53: Monitor mesh VPN connectivity for all fleet nodes.

        Pings each node's mesh_ip, updates mesh_status/mesh_latency_ms
        in remote_nodes, and logs to mesh_health_log. Triggers fleet cache
        refresh on status transitions (disconnected→connected or vice versa).
        """
        pass

    def _save_model_state(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py save_model_state()
        Job #46: Save current loaded models to DB for restart recovery."""
        pass

    def _hourly_uncommitted_check(self):
        """Job #42: Monitor for uncommitted changes in the platform directory."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd="/mnt/archie_brain",
                capture_output=True,
                text=True,
                timeout=15,
            )
            lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
            if not lines:
                logger.debug("Uncommitted change monitor: working directory clean")
                return

            modules = set()
            for line in lines:
                filepath = line[3:].strip().split(" -> ")[-1]  # handle renames
                parts = filepath.split("/")
                if parts[0] == "platform_v2" and len(parts) > 2 and parts[1] == "tools":
                    modules.add(parts[2])
                elif parts[0] == "ai_bridge":
                    modules.add("ai_bridge")
                elif parts[0] == "platform_v2":
                    modules.add("app_core")
                else:
                    modules.add(parts[0])

            logger.info(
                "Uncommitted changes detected in %d modules: %s (%d files)",
                len(modules),
                ", ".join(sorted(modules)),
                len(lines),
            )
        except Exception as e:
            logger.warning(f"Uncommitted change monitor failed: {e}")

    # ------------------------------------------------------------------
    # Job #48: Auto-Execute Approved Dev Pipeline Proposals
    # ------------------------------------------------------------------

    def _auto_execute_proposals(self):
        """Job #48: Process approved improvement proposals by dispatching to coding agents."""
        try:
            from database import get_db_cursor
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            if not dispatcher:
                logger.warning("[Fix Processor] Bridge dispatcher not available")
                return

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, title, description, category, priority,
                           code_changes, metadata->>'file_path' AS file_path, plan_steps,
                           retry_count, required_skills
                    FROM improvement_proposals
                    WHERE status = 'approved'
                      AND assigned_agent_id IS NULL
                      AND retry_count < 3
                      AND (metadata->>'source' IS NULL OR metadata->>'source' != 'code_health_audit')
                    ORDER BY
                        CASE priority
                            WHEN 'critical' THEN 1
                            WHEN 'high' THEN 2
                            WHEN 'medium' THEN 3
                            WHEN 'low' THEN 4
                            ELSE 5
                        END,
                        proposed_at ASC
                    LIMIT 3
                """
                )
                proposals = cur.fetchall()
                # get_db_cursor yields RealDictCursor rows (KB #268832) but this
                # pipeline indexes tuples (proposal[0], proposal[6], ...) — the
                # resulting KeyError printed as 'Job failed: 0' and kept Job #48
                # dead even after the file_path fix (layered bug). Normalize.
                proposals = [
                    (
                        (
                            r["id"],
                            r["title"],
                            r["description"],
                            r["category"],
                            r["priority"],
                            r["code_changes"],
                            r["file_path"],
                            r["plan_steps"],
                            r["retry_count"],
                            r["required_skills"],
                        )
                        if isinstance(r, dict)
                        else r
                    )
                    for r in proposals
                ]

            if not proposals:
                logger.debug("[Fix Processor] No approved proposals to process")
                return

            succeeded = 0
            failed = 0

            for proposal in proposals:
                try:
                    self._dispatch_fix_to_agent(proposal, dispatcher)
                    succeeded += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"[Fix Processor] Failed proposal #{proposal[0]}: {e}")
                    try:
                        from database import get_db_cursor as _gdc

                        with _gdc(commit=True) as (conn2, cur2):
                            cur2.execute(
                                """
                                UPDATE improvement_proposals
                                SET retry_count = retry_count + 1,
                                    last_retry_at = NOW(),
                                    status = CASE
                                        WHEN retry_count >= 2 THEN 'needs_claude'
                                        ELSE 'approved'
                                    END,
                                    escalation_status = CASE
                                        WHEN retry_count >= 2 THEN 'human_only'
                                        ELSE escalation_status
                                    END
                                WHERE id = %s
                            """,
                                (proposal[0],),
                            )
                    except Exception as db_err:
                        logger.error(f"[Fix Processor] DB update failed for proposal #{proposal[0]}: {db_err}")

            logger.info(
                f"[Fix Processor] Processed {succeeded + failed} proposals, " f"{succeeded} succeeded, {failed} failed"
            )

        except Exception as e:
            logger.error(f"[Fix Processor] Job failed: {e}")

    def _dispatch_fix_to_agent(self, proposal, dispatcher):
        """Dispatch a single fix proposal to a coding agent via Bridge."""
        from database import get_db_cursor
        from psycopg2.extras import Json

        proposal_id = proposal[0]  # id
        title = proposal[1]  # title
        description = proposal[2]  # description
        category = proposal[3]  # category
        priority = proposal[4]  # priority
        file_path = proposal[6] or proposal[5] or ""  # file_path or code_changes

        # 1. Read the target file
        full_path = f"/mnt/archie_brain/{file_path}" if file_path else None
        file_content = ""
        if full_path:
            try:
                with open(full_path, "r") as f:
                    file_content = f.read()
            except FileNotFoundError:
                logger.warning(f"[Fix Processor] File not found: {file_path}")
            except Exception as read_err:
                logger.warning(f"[Fix Processor] Cannot read {file_path}: {read_err}")

        # 2. Find matching fix pattern from knowledge_base
        fix_pattern = self._find_fix_pattern(category)

        # 3. Build the prompt
        prompt = self._build_fix_prompt(
            title=title,
            description=description,
            category=category,
            priority=priority,
            file_path=file_path,
            file_content=file_content,
            fix_pattern=fix_pattern,
        )

        system_prompt = (
            "You are an Engineering & Technology department agent on A.R.C.H.I.E. "
            "Fix the code issue described. Return ONLY valid JSON with keys: "
            "modified_code, explanation, confidence (0-1), files_changed (array), "
            "lines_modified (array of line numbers), breaking_changes (bool)."
        )

        # 4. Find an active ENGINEERING agent and mark proposal as assigned
        agent = None
        fleet_agent_info = None
        dispatch_source = "hub"

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                SELECT a.id, a.name FROM agents a
                WHERE a.department = 'Engineering & Technology'
                  AND a.shift_state = 'active'
                ORDER BY a.name
                LIMIT 1
            """
            )
            agent = cur.fetchone()
            if isinstance(agent, dict):  # RealDictCursor row → tuple (KB #268832)
                agent = (agent["id"], agent["name"])

            if not agent:
                logger.info("[Fix Processor] No hub ENGINEERING agent, trying fleet agents...")
                # Fallback: try fleet agents on remote nodes
                fleet_agent_info = dispatcher._find_fleet_agent("ENGINEERING", "code_fix")
                if not fleet_agent_info:
                    logger.warning("[Fix Processor] No hub or fleet ENGINEERING agent available")
                    return
                dispatch_source = "fleet"
                # Use hub_agent_id from fleet agent for DB assignment (FK to agents table)
                assigned_id = fleet_agent_info.get("hub_agent_id")
                if assigned_id:
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET status = 'agent_assigned',
                            assigned_agent_id = %s
                        WHERE id = %s
                    """,
                        (assigned_id, proposal_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET status = 'agent_assigned'
                        WHERE id = %s
                    """,
                        (proposal_id,),
                    )
                logger.info(
                    f"[Fix Processor] Fleet agent {fleet_agent_info['agent_name']} "
                    f"on node {fleet_agent_info.get('node_name', '?')} assigned to proposal #{proposal_id}"
                )
            else:
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET status = 'agent_assigned',
                        assigned_agent_id = %s
                    WHERE id = %s
                """,
                    (agent[0], proposal_id),
                )

        # 5. Dispatch to agent via Bridge (hub) or fleet node
        response_text = None

        if dispatch_source == "hub":
            # Hub dispatch via Bridge request_work
            result = dispatcher.request_work(
                capability="code_fix",
                prompt=prompt,
                module_id="dev_pipeline",
                system_prompt=system_prompt,
                json_mode=True,
            )

            if not result or not result.success:
                error_msg = getattr(result, "error", "unknown") if result else "no result"
                logger.warning(
                    f"[Fix Processor] Hub dispatch failed for proposal #{proposal_id}: {error_msg}, "
                    "trying fleet fallback..."
                )
                # Fallback: try fleet agent when hub dispatch fails
                fleet_agent_info = dispatcher._find_fleet_agent("ENGINEERING", "code_fix")
                if fleet_agent_info:
                    dispatch_source = "fleet"
                    logger.info(
                        f"[Fix Processor] Fleet fallback: {fleet_agent_info['agent_name']} "
                        f"on node {fleet_agent_info.get('node_name', '?')}"
                    )
                else:
                    logger.error(f"[Fix Processor] No fleet fallback available for proposal #{proposal_id}")
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """
                            UPDATE improvement_proposals
                            SET status = 'approved', assigned_agent_id = NULL,
                                retry_count = retry_count + 1,
                                last_retry_at = NOW()
                            WHERE id = %s
                        """,
                            (proposal_id,),
                        )
                    return
            else:
                response_text = result.response

        if dispatch_source == "fleet" and response_text is None:
            # Fleet dispatch via node Ollama API
            fleet_result = dispatcher._dispatch_to_node(
                agent_info=fleet_agent_info,
                prompt=prompt,
                system_prompt=system_prompt,
                capability="code_fix",
                module_id="dev_pipeline",
                department="Engineering & Technology",
            )

            if not fleet_result or not fleet_result.get("success"):
                logger.error(f"[Fix Processor] Fleet dispatch failed for proposal #{proposal_id}")
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET status = 'approved', assigned_agent_id = NULL,
                            retry_count = retry_count + 1,
                            last_retry_at = NOW()
                        WHERE id = %s
                    """,
                        (proposal_id,),
                    )
                return
            response_text = fleet_result["response"]
            # Update assigned agent to fleet agent if we fell back mid-dispatch
            fleet_hub_id = fleet_agent_info.get("hub_agent_id")
            if fleet_hub_id:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET assigned_agent_id = %s
                        WHERE id = %s
                    """,
                        (fleet_hub_id, proposal_id),
                    )

        # 6. Parse agent response
        try:
            fix_data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"[Fix Processor] Invalid JSON from agent for proposal #{proposal_id}")
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET status = 'approved', assigned_agent_id = NULL,
                        retry_count = retry_count + 1
                    WHERE id = %s
                """,
                    (proposal_id,),
                )
            return

        # 7. Store agent's fix in proposal
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE improvement_proposals
                SET contractor_proposal = %s,
                    status = 'in_progress'
                WHERE id = %s
            """,
                (Json(fix_data), proposal_id),
            )

        # 8. Write to sandbox if available (v1: just log, no sandbox tests yet)
        try:
            from sandbox_manager import SandboxManager

            sm = SandboxManager()
            sandbox_path = sm.write_proposal_file(proposal_id, file_path, fix_data.get("modified_code", ""))
            logger.info(f"[Fix Processor] Proposal #{proposal_id} sandbox file written: {sandbox_path}")
        except ImportError:
            logger.debug("[Fix Processor] SandboxManager not available, skipping sandbox write")
        except Exception as sandbox_err:
            logger.warning(f"[Fix Processor] Sandbox write failed for proposal #{proposal_id}: {sandbox_err}")

        dispatch_agent_name = (
            fleet_agent_info["agent_name"]
            if fleet_agent_info and dispatch_source == "fleet"
            else (agent[1] if agent else "unknown")
        )
        dispatch_node = (
            fleet_agent_info.get("node_name", "remote") if fleet_agent_info and dispatch_source == "fleet" else "hub"
        )
        logger.info(
            f"[Fix Processor] Proposal #{proposal_id} '{title}' dispatched successfully "
            f"via {dispatch_source} agent={dispatch_agent_name} node={dispatch_node} "
            f"(confidence={fix_data.get('confidence', 'N/A')})"
        )

    def _find_fix_pattern(self, category):
        """Look up a fix pattern from knowledge_base matching the proposal category."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT content FROM knowledge_base
                    WHERE category = 'code_health'
                      AND knowledge_type = 'fix_pattern'
                      AND (tags::text ILIKE %s OR content ILIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT 1
                """,
                    (f"%{category}%", f"%{category}%"),
                )
                row = cur.fetchone()
                if row:
                    return row["content"] if isinstance(row, dict) else row[0]
        except Exception as e:
            logger.debug(f"[Fix Processor] Fix pattern lookup failed for '{category}': {e}")
        return ""

    def _build_fix_prompt(self, title, description, category, priority, file_path, file_content, fix_pattern):
        """Construct the prompt for a code fix agent."""
        parts = [
            "FIX REQUEST",
            "===========",
            f"Issue Type: {category}",
            f"Priority: {priority}",
            f"File: {file_path}",
            f"Title: {title}",
            f"Description: {description}",
        ]

        if file_content:
            # Truncate very large files to avoid blowing context
            content = file_content[:15000]
            if len(file_content) > 15000:
                content += f"\n\n... (truncated, full file is {len(file_content)} chars)"
            parts.append(f"\nCURRENT CODE:\n```\n{content}\n```")

        if fix_pattern:
            parts.append(f"\nFIX PATTERN:\n{fix_pattern}")

        parts.append(
            "\nRespond with JSON:\n"
            '{"modified_code": "...full file content with fix applied...", '
            '"explanation": "...what was changed and why...", '
            '"confidence": 0.0, '
            '"files_changed": ["path/to/file.py"], '
            '"lines_modified": [45, 46], '
            '"breaking_changes": false}'
        )

        return "\n".join(parts)

    def _consciousness_analysis_batch(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py consciousness_analysis_batch()"""
        pass

    def _consciousness_embedding_batch(self):
        """DEPRECATED (Phase 5): Moved to consciousness/jobs.py consciousness_embedding_batch()"""
        pass

    # ── Job #59 — Standalone Health Monitor ─────────────────────────────

    _standalone_last_status = {}

    def _check_standalone_health(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py check_standalone_health()
        Job #59: Monitor standalone product health, alert on downtime."""
        pass

    def _department_metrics_rollup(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py department_metrics_rollup()
        Job #60: Department metrics rollup — daily at 2:00 AM.
        Owned by Analytics & Intelligence (S.P.E.C.T.R.A.)."""
        pass

    def _renew_fleet_ssl(self):
        """DEPRECATED (Phase 5): Moved to services/fleet_jobs.py renew_fleet_ssl()
        Job #61: Renew wildcard SSL cert if expiring within 30 days.
        Owned by Security & Compliance (V.I.G.I.L.)."""
        pass

    # ── Job #62 — Social Video: Generate Content ──────────────────────────

    def _social_video_generate_content(self):
        """Job #62: Generate social video content from templates every 4 hours."""
        import random

        try:
            from tools.media_studio.services import social_video_service as svs

            # Check budget
            budget = svs.check_budget()
            if not budget.get("can_generate", False):
                logger.info("[SocialVideo] Budget limit reached, skipping generation")
                return

            # Check pending queue — skip if 5+ items in-flight or draft
            generating = svs.get_queue_items(status="generating") or []
            drafts = svs.get_queue_items(status="draft") or []
            if len(generating) + len(drafts) >= 5:
                logger.info("[SocialVideo] Queue has %d pending items, skipping", len(generating) + len(drafts))
                return

            # Pick content type by weighted random
            content_type = random.choices(
                ["motivational", "agent_moment"],
                weights=[7, 3],
                k=1,
            )[0]

            # Get active templates for this type
            templates = svs.get_templates(content_type=content_type, active_only=True)
            if not templates:
                logger.info("[SocialVideo] No active templates for type=%s", content_type)
                return

            template = random.choice(templates)

            # Build variables dict
            if content_type == "agent_moment":
                agent = svs.pick_agent_for_content(content_type)
                agent_id = agent.get("id")
                variables = {
                    "agent_name": agent.get("display_name") or agent.get("name", ""),
                    "department": agent.get("department", ""),
                    "personality_trait": (agent.get("personality", "") or "")[:100],
                    "personality_note": "",
                    "project_note": "",
                }
            else:
                agent_id = None
                quotes = [
                    ("The only way to do great work is to love what you do.", "Steve Jobs"),
                    ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
                    (
                        "Success is not final, failure is not fatal: it is the courage to continue that counts.",
                        "Winston Churchill",
                    ),
                    ("It's not about ideas. It's about making ideas happen.", "Ralph Marston"),
                    ("Believe you can and you're halfway there.", "Theodore Roosevelt"),
                    ("The secret of getting ahead is getting started.", "Mark Twain"),
                    ("A journey of a thousand miles begins with a single step.", "Chinese Proverb"),
                    ("In the middle of every difficulty lies opportunity.", "Albert Einstein"),
                ]
                quote_text, quote_author = random.choice(quotes)
                scene = random.choice(["mountains", "ocean", "city", "forest", "starry night"])
                variables = {
                    "quote": quote_text,
                    "author": quote_author,
                    "scene": scene,
                }

            # Render template
            rendered = svs.render_template(template["id"], variables)
            if not rendered:
                logger.warning("[SocialVideo] Template render returned None for template_id=%s", template["id"])
                return

            # Determine approval tier and auto-approve eligibility
            approval_tier = rendered.get("approval_tier", "manual")
            if content_type == "agent_moment" and svs.should_auto_approve(agent_id, content_type):
                approval_tier = "auto"

            # Create queue item
            item = svs.create_queue_item(
                content_type=content_type,
                prompt=rendered.get("prompt", ""),
                caption=rendered.get("caption", ""),
                hashtags=rendered.get("hashtags"),
                target_platforms=rendered.get("platforms"),
                agent_id=agent_id,
                template_id=template["id"],
                approval_tier=approval_tier,
                generation_params=rendered.get("video_params"),
                created_by="agent_loop",
            )
            logger.info(
                "[SocialVideo] Created queue item id=%s type=%s tier=%s", item.get("id"), content_type, approval_tier
            )

            # Trigger generation worker
            from tools.media_studio.services.social_video_worker import process_queue

            process_queue()

        except Exception as e:
            logger.error("[SocialVideo] Content generation job failed: %s", e)

    # ── Job #63 — Social Video: Auto-Approve ──────────────────────────────

    def _social_video_auto_approve(self):
        """Job #63: Auto-approve eligible social video queue items every 15 minutes."""
        try:
            from tools.media_studio.services import social_video_service as svs

            items = svs.get_queue_items(status="ready", limit=20) or []
            for item in items:
                if item.get("approval_tier") == "auto":
                    svs.approve_item(item["id"])
                    logger.info("[SocialVideo] Auto-approved queue item id=%s", item["id"])

        except Exception as e:
            logger.error("[SocialVideo] Auto-approve job failed: %s", e)

    # ── Job #64 — Social Video: Publish Scheduled ─────────────────────────

    def _social_video_publish(self):
        """Job #64: Publish scheduled social video items every 5 minutes."""
        import json as _json
        import os as _os
        from datetime import datetime as _dt, timezone as _tz

        try:
            from tools.media_studio.services import social_video_service as svs

            now = _dt.now(_tz.utc)
            items = svs.get_queue_items(status="scheduled", limit=10) or []

            for item in items:
                try:
                    scheduled_at = item.get("scheduled_at")
                    if scheduled_at is None:
                        continue
                    # Normalize to UTC-aware datetime if needed
                    if isinstance(scheduled_at, str):
                        scheduled_at = _dt.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                    if scheduled_at.tzinfo is None:
                        scheduled_at = scheduled_at.replace(tzinfo=_tz.utc)
                    if scheduled_at > now:
                        continue

                    video_path = item.get("video_path", "")
                    if not _os.path.exists(video_path):
                        logger.warning("[SocialVideo] Video file not found: %s", video_path)
                        continue

                    caption = item.get("caption", "")
                    hashtags = item.get("hashtags", [])
                    platforms = item.get("target_platforms", [])
                    post_urls = {}

                    for platform in platforms:
                        try:
                            if platform == "indeed":
                                from tools.social_media.platform_clients import get_indeed_client

                                result = get_indeed_client().post_video(video_path, caption, hashtags)
                                if result:
                                    post_urls[platform] = result
                        except Exception as platform_err:
                            logger.error(
                                "[SocialVideo] Publish failed for platform=%s item=%s: %s",
                                platform,
                                item["id"],
                                platform_err,
                            )

                    new_status = "posted" if post_urls else "failed"
                    svs.update_queue_item(
                        item["id"],
                        status=new_status,
                        posted_at=now,
                        post_urls=_json.dumps(post_urls),
                    )
                    logger.info(
                        "[SocialVideo] Published item id=%s status=%s platforms=%s",
                        item["id"],
                        new_status,
                        list(post_urls.keys()),
                    )

                except Exception as item_err:
                    logger.error("[SocialVideo] Publish error for item id=%s: %s", item.get("id"), item_err)

        except Exception as e:
            logger.error("[SocialVideo] Publish job failed: %s", e)

    def _social_video_slideshow_render(self):
        """Pick up draft social_video_queue items with images and render AutoShorts slideshows."""
        try:
            from tools.media_studio.services import social_video_service as svs
            from tools.media_studio.services.slideshow_generator import generate_slideshow
            from database import get_db_cursor

            items = svs.svq_get_renderable(limit=2)
            if not items:
                return

            for item in items:
                item_id = item["id"]
                media_ids = item.get("media_ids") or []
                if not svs.svq_start_render(item_id):
                    continue  # Already claimed by another worker

                logger.info("[SlideshowRender] Rendering item %s with %d images", item_id, len(media_ids))

                # Resolve image file paths from media_library
                image_paths = []
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT file_path FROM media_library WHERE id = ANY(%s) AND is_deleted=false ORDER BY array_position(%s, id)",
                        (media_ids, media_ids),
                    )
                    for row in cur.fetchall():
                        fp = row["file_path"]
                        if not fp.startswith("/"):
                            fp = "/" + fp
                        # Resolve to filesystem path
                        if fp.startswith("/static/"):
                            from tools.media_studio.services.slideshow_generator import _APP_ROOT

                            abs_path = _APP_ROOT + fp
                        else:
                            abs_path = fp
                        if os.path.exists(abs_path):
                            image_paths.append(abs_path)
                        else:
                            logger.warning("[SlideshowRender] Image not found on disk: %s", abs_path)

                if not image_paths:
                    svs.svq_fail_render(item_id, "No valid image files found for selected media_ids")
                    continue

                result = generate_slideshow(
                    image_paths=image_paths,
                    quote_text=item.get("quote_text") or "",
                    title=item.get("title") or "",
                    audio_mode=item.get("audio_mode") or "music",
                    target_duration=25,
                )

                if result.get("success"):
                    from tools.media_studio.services.slideshow_generator import _APP_ROOT as _SG_ROOT

                    def _to_web(p):
                        if p and p.startswith(_SG_ROOT):
                            return p[len(_SG_ROOT) :]
                        return p or ""

                    web_vid = _to_web(result["video_path"])
                    web_thumb = _to_web(result.get("thumbnail_path") or "")
                    svs.svq_finish_render(item_id, web_vid, web_thumb)
                    logger.info("[SlideshowRender] Item %s rendered → %s", item_id, web_vid)
                else:
                    svs.svq_fail_render(item_id, result.get("error", "Unknown render error"))
                    logger.error("[SlideshowRender] Item %s failed: %s", item_id, result.get("error"))

        except Exception as e:
            logger.exception("[SlideshowRender] Worker error: %s", e)

    def _social_content_auto_suggest(self):
        """Daily 8am: auto-generate content for calendar slots + detect gaps → Telegram."""
        try:
            from tools.media_studio.services.calendar_service import (
                generate_themed_caption,
                get_empty_days_this_week,
                get_slots_due_for_generation,
            )
            from tools.media_studio.services.social_video_service import svq_create

            due = get_slots_due_for_generation(days_ahead=3)
            for slot in due:
                agent_id = slot.get("featured_agent_id") or slot.get("agent_id_val")
                theme_id = slot.get("theme_id")
                if not agent_id or not theme_id:
                    continue
                caption = generate_themed_caption(agent_id, theme_id)
                if not caption:
                    logger.warning("[AutoSuggest] Caption generation failed for slot %s", slot.get("id"))
                    continue
                svq_create(
                    title=slot.get("theme_name", "Untitled"),
                    quote_text=caption,
                    media_ids=[],
                    audio_mode="music",
                    platform=slot.get("platform", "linkedin"),
                    scheduled_at=None,
                    user_id=1,
                    theme_id=theme_id,
                )
                logger.info("[AutoSuggest] Queued slot %s (theme: %s)", slot.get("id"), slot.get("theme_name"))

            # Gap detection: notify if tomorrow has no content
            from datetime import date, timedelta

            tomorrow_dow = (date.today() + timedelta(days=1)).weekday()
            empty = get_empty_days_this_week()
            if tomorrow_dow in empty:
                _day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                try:
                    from services.telegram_service import send_info

                    send_info(
                        f"\U0001f4c5 S.I.G.N.A.L. Calendar: {_day_names[tomorrow_dow]} has no content queued. "
                        "Visit Media Studio → Social Video to create a post."
                    )
                except Exception as tg_err:
                    logger.debug("[AutoSuggest] Telegram notify failed (non-blocking): %s", tg_err)

        except Exception as e:
            logger.exception("[AutoSuggest] Worker error: %s", e)

    # ── V.I.G.I.L. Handler Methods ──

    def _vigilil_network_health(self):
        """Check all security services are running. Auto-restart if down."""
        try:
            import subprocess
            from tools.security_network.ntopng_service import NtopngService
            from tools.security_network.nagios_service import NagiosService

            issues = []

            # Check ntopng
            try:
                nt = NtopngService()
                if not nt.is_healthy():
                    issues.append("ntopng is not responding")
                    subprocess.run(["docker", "restart", "network_ntopng"], capture_output=True, timeout=30)
            except Exception as e:
                issues.append(f"ntopng check failed: {e}")

            # Check Nagios
            try:
                ng = NagiosService()
                if not ng.is_healthy():
                    issues.append("Nagios is not responding")
            except Exception as e:
                issues.append(f"Nagios check failed: {e}")

            # Check AdGuard
            try:
                ag_user = os.getenv("ADGUARD_USER", "kytran")
                ag_pass = os.getenv("ADGUARD_PASS", "")
                result = subprocess.run(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        "-u",
                        f"{ag_user}:{ag_pass}",
                        "http://network_adguard:80/control/status",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip() != "200":
                    issues.append("AdGuard is not responding")
            except Exception as e:
                issues.append(f"AdGuard check failed: {e}")

            # NPM (nginx_proxy_manager) health check REMOVED 2026-06-28 — NPM was
            # decommissioned (ADR-853); Beacon (2.25.170.252) is the sole hub front
            # door. The old check inspected/restarted a container that no longer
            # exists, so EVERY cycle it appended a FALSE "NPM not running — all
            # HTTPS subdomains affected" high alert + ran a no-op docker restart.
            # 3rd missed NPM revival vector (after infra_heartbeat_service.py +
            # fleet_jobs.py). KB #276161/#276817.

            if issues:
                self._create_network_alert(
                    "service_down",
                    "high",
                    "health_monitor",
                    f"Service issues detected: {len(issues)}",
                    {"issues": issues},
                )
        except Exception as e:
            logger.error(f"V.I.G.I.L. network health check failed: {e}")

    def _vigilil_traffic_aggregator(self):
        """Pull traffic data from ntopng and DNS stats from AdGuard into DB.

        Uses UPSERT to prevent duplicates — takes the MAX of bytes seen
        for each device per hour bucket (ntopng reports cumulative bytes).
        """
        try:
            from tools.security_network.ntopng_service import NtopngService
            from database import get_db_cursor
            from datetime import datetime

            nt = NtopngService()
            hosts = nt.get_hosts()

            if not hosts:
                return

            hour_bucket = datetime.now().replace(minute=0, second=0, microsecond=0)
            count = 0

            with get_db_cursor(commit=True) as (conn, cur):
                for host in hosts:
                    if not isinstance(host, dict):
                        continue
                    mac = host.get("mac", "")
                    ip = host.get("ip", "")
                    if not ip or ip.startswith("ff") or ip.startswith("239."):
                        continue  # skip multicast
                    bytes_in = host.get("bytes.rcvd", 0)
                    bytes_out = host.get("bytes.sent", 0)
                    if bytes_in == 0 and bytes_out == 0:
                        continue
                    cur.execute(
                        """INSERT INTO network_traffic_stats
                               (device_mac, device_ip, bytes_in, bytes_out, protocol, hour_bucket)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT (device_ip, hour_bucket)
                           DO UPDATE SET
                               bytes_in = GREATEST(network_traffic_stats.bytes_in, EXCLUDED.bytes_in),
                               bytes_out = GREATEST(network_traffic_stats.bytes_out, EXCLUDED.bytes_out),
                               device_mac = COALESCE(NULLIF(EXCLUDED.device_mac, ''), network_traffic_stats.device_mac)""",
                        (
                            mac,
                            ip,
                            bytes_in,
                            bytes_out,
                            host.get("l7proto", "unknown"),
                            hour_bucket,
                        ),
                    )
                    count += 1
            logger.info(f"V.I.G.I.L.: Aggregated traffic for {count} hosts")
        except Exception as e:
            logger.error(f"V.I.G.I.L. traffic aggregator failed: {e}")

    def _vigilil_nagios_sync(self):
        """Sync Nagios check results into local cache table."""
        try:
            from tools.security_network.nagios_service import NagiosService
            from database import get_db_cursor

            ng = NagiosService()
            results = ng.get_all_for_cache()

            if not results:
                return

            with get_db_cursor(commit=True) as (conn, cur):
                for r in results:
                    cur.execute(
                        """INSERT INTO nagios_check_results (host_name, service_description, status, output, performance_data, last_check, updated_at)
                           VALUES (%s, %s, %s, %s, %s, to_timestamp(%s), NOW())
                           ON CONFLICT (host_name, COALESCE(service_description, ''))
                           DO UPDATE SET status = EXCLUDED.status, output = EXCLUDED.output,
                                         performance_data = EXCLUDED.performance_data,
                                         last_check = EXCLUDED.last_check, updated_at = NOW()""",
                        (
                            r["host_name"],
                            r["service_description"],
                            r["status"],
                            r["output"],
                            r["performance_data"],
                            r["last_check"],
                        ),
                    )
            logger.info(f"V.I.G.I.L.: Synced {len(results)} Nagios check results")
        except Exception as e:
            logger.error(f"V.I.G.I.L. Nagios sync failed: {e}")

    def _vigilil_device_watcher(self):
        """Detect new/unknown devices on the network."""
        try:
            from tools.security_network.ntopng_service import NtopngService
            from database import get_db_cursor

            nt = NtopngService()
            hosts = nt.get_hosts()

            if not hosts:
                return

            with get_db_cursor(commit=True) as (conn, cur):
                for host in hosts:
                    if not isinstance(host, dict):
                        continue
                    mac = host.get("mac", "")
                    ip = host.get("ip", "")
                    name = host.get("name", "")

                    if not mac or mac == "00:00:00:00:00:00":
                        continue

                    cur.execute("SELECT id, is_registered FROM network_devices WHERE mac_address = %s", (mac,))
                    row = cur.fetchone()

                    if row is None:
                        cur.execute(
                            """INSERT INTO network_devices (mac_address, ip_address, hostname, security_zone, status, is_registered, first_seen_at, last_seen_at)
                               VALUES (%s, %s, %s, 'quarantined', 'active', FALSE, NOW(), NOW())
                               ON CONFLICT (mac_address) DO UPDATE SET last_seen_at = NOW(), ip_address = EXCLUDED.ip_address""",
                            (mac, ip, name),
                        )
                        self._create_network_alert(
                            "new_device",
                            "medium",
                            "device_watcher",
                            f"New device detected: {name or mac} ({ip})",
                            {"mac": mac, "ip": ip, "hostname": name},
                        )
                        logger.info(f"V.I.G.I.L.: New device detected — {mac} ({ip})")
                    else:
                        cur.execute(
                            "UPDATE network_devices SET last_seen_at = NOW(), ip_address = %s WHERE mac_address = %s",
                            (ip, mac),
                        )
        except Exception as e:
            logger.error(f"V.I.G.I.L. device watcher failed: {e}")

    def _vigilil_dns_anomaly(self):
        """Check AdGuard for DNS anomalies — tunneling, tracking spikes."""
        try:
            from tools.security_network.adguard_service import AdGuardService

            ag = AdGuardService()
            stats = ag.get_stats()

            total = stats.get("num_dns_queries", 0)
            blocked = stats.get("num_blocked_filtering", 0)
            if total > 100 and blocked / total > 0.5:
                self._create_network_alert(
                    "dns_anomaly",
                    "medium",
                    "dns_anomaly_detector",
                    f"High DNS block rate: {blocked}/{total} ({blocked/total*100:.0f}%)",
                    {"total_queries": total, "blocked": blocked, "block_rate": blocked / total},
                )
        except Exception as e:
            logger.error(f"V.I.G.I.L. DNS anomaly detector failed: {e}")

    def _vigilil_log_health(self):
        """Check log file sizes — detect spam before disk fills."""
        try:
            import os

            log_files = {
                "/var/log/syslog": 500_000_000,
                "/var/log/auth.log": 500_000_000,
                "/var/log/kern.log": 500_000_000,
                "/var/log/ufw.log": 200_000_000,
            }

            for path, threshold in log_files.items():
                try:
                    size = os.path.getsize(path)
                    if size > threshold:
                        size_mb = size / 1_000_000
                        threshold_mb = threshold / 1_000_000
                        self._create_network_alert(
                            "log_overflow",
                            "high",
                            "log_health_monitor",
                            f"Log file {path} is {size_mb:.0f}MB (threshold: {threshold_mb:.0f}MB)",
                            {"file": path, "size_bytes": size, "threshold_bytes": threshold},
                        )
                        logger.warning(f"V.I.G.I.L.: Log file {path} is {size_mb:.0f}MB — exceeds threshold")
                except FileNotFoundError:
                    pass
        except Exception as e:
            logger.error(f"V.I.G.I.L. log health check failed: {e}")

    def _vigilil_daily_report(self):
        """Generate and deliver daily consumption reports."""
        try:
            from tools.security_network.report_service import ReportService

            svc = ReportService()
            device_report = svc.generate_daily_device_report()
            user_report = svc.generate_daily_user_report()

            total_bytes = device_report.get("total_bytes", 0)
            total_devices = device_report.get("total_devices", 0)
            total_users = user_report.get("total_users", 0)

            logger.info(
                f"V.I.G.I.L.: Daily report generated — "
                f"{total_devices} devices, {total_users} users, "
                f"{total_bytes / 1_000_000_000:.1f}GB total"
            )
            # TODO: Telegram + email delivery (future integration)
        except Exception as e:
            logger.error(f"V.I.G.I.L. daily report failed: {e}")

    def _vigilil_threat_responder(self):
        """Check for active threats and auto-respond."""
        try:
            from tools.security_network.fail2ban_service import Fail2banService
            from database import get_db_cursor

            f2b = Fail2banService()
            jails = f2b.get_all_jail_statuses()

            for jail in jails:
                if jail.get("currently_banned", 0) > 0:
                    for ip in jail.get("banned_ips", []):
                        with get_db_cursor() as (conn, cur):
                            cur.execute(
                                """SELECT id FROM network_alerts
                                   WHERE alert_type = 'ip_banned' AND source = 'threat_responder'
                                   AND details->>'ip' = %s AND created_at > NOW() - INTERVAL '1 hour'""",
                                (ip,),
                            )
                            if cur.fetchone() is None:
                                self._create_network_alert(
                                    "ip_banned",
                                    "high",
                                    "threat_responder",
                                    f"IP {ip} banned by fail2ban jail {jail.get('jail', 'unknown')}",
                                    {
                                        "ip": ip,
                                        "jail": jail.get("jail", ""),
                                        "total_banned": jail.get("total_banned", 0),
                                    },
                                )
        except Exception as e:
            logger.error(f"V.I.G.I.L. threat responder failed: {e}")

    def _create_network_alert(self, alert_type, severity, source, title, details=None):
        """Helper to create a network alert in the DB."""
        try:
            from database import get_db_cursor
            from psycopg2.extras import Json

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO network_alerts (alert_type, severity, source, title, details)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (alert_type, severity, source, title, Json(details or {})),
                )
        except Exception as e:
            logger.error(f"Failed to create network alert: {e}")

    def _run_quality_review(self):
        """Job: Knowledge Quality Review — score unscored KB entries every 2 hours."""
        try:
            from services.quality_review_job import run_quality_review

            run_quality_review()
        except Exception as e:
            logger.error("Quality review job failed: %s", e)

    def _run_login_anomaly_check(self):
        """Alert on accounts with excessive successful logins in 24h."""
        import time as _time

        _start = _time.time()
        processed = 0
        try:
            from database import get_db_cursor
            from services.time_utils import now_utc
            from services.telegram_service import send_security

            # Configurable threshold (default: 10 logins / 24h)
            threshold = 10
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT value FROM system_config WHERE key = 'login_anomaly_threshold'")
                row = cur.fetchone()
                if row and row[0]:
                    try:
                        threshold = int(row[0])
                    except (ValueError, TypeError):
                        pass

            # Find users exceeding threshold in last 24h
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT a.user_id, u.username, u.email,
                           COUNT(*) AS login_count,
                           array_agg(DISTINCT a.ip_address) AS ips,
                           MIN(a.created_at) AS first_login,
                           MAX(a.created_at) AS last_login
                    FROM audit_log a
                    JOIN users u ON a.user_id = u.id
                    WHERE a.action = 'login_success'
                      AND a.created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY a.user_id, u.username, u.email
                    HAVING COUNT(*) >= %s
                    """,
                    [threshold],
                )
                rows = cur.fetchall() or []

            processed = len(rows)
            now = now_utc()

            for row in rows:
                user_id, username, email, login_count, ips, first_login, last_login = row
                try:
                    # Rate-limit: one alert per user per 24h
                    alert_key = f"anomaly_alert_{user_id}"
                    with get_db_cursor() as (conn, cur):
                        cur.execute("SELECT value FROM system_config WHERE key = %s", [alert_key])
                        existing = cur.fetchone()
                    if existing and existing[0]:
                        try:
                            import datetime as _dt

                            last_alert = _dt.datetime.fromisoformat(existing[0])
                            if last_alert.tzinfo is None:
                                last_alert = last_alert.replace(tzinfo=_dt.timezone.utc)
                            if (now - last_alert).total_seconds() < 86400:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # Send Telegram security alert
                    ip_list = ", ".join(str(ip) for ip in (ips or []) if ip) or "unknown"
                    fmt = "%H:%M"
                    window = (
                        f"{first_login.strftime(fmt) if first_login else '?'}"
                        f" → {last_login.strftime(fmt) if last_login else '?'}"
                    )
                    send_security(
                        title="Login Anomaly Detected",
                        message=(
                            f"User: {username} ({email})\n"
                            f"Logins in 24h: {login_count}\n"
                            f"IPs: {ip_list}\n"
                            f"Window: {window}"
                        ),
                    )

                    # Mark alerted (suppress for 24h)
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """INSERT INTO system_config (key, value)
                               VALUES (%s, %s)
                               ON CONFLICT (key) DO UPDATE
                               SET value = EXCLUDED.value, updated_at = NOW()""",
                            [alert_key, now.isoformat()],
                        )
                    logger.info(
                        "login_anomaly_check: alert sent for user_id=%s (%d logins)",
                        user_id,
                        login_count,
                    )
                except Exception as _user_err:
                    logger.error(
                        "login_anomaly_check: failed for user_id=%s: %s",
                        user_id,
                        _user_err,
                    )

            duration_ms = int((_time.time() - _start) * 1000)
            self._log_cycle("login_anomaly_check", processed, 0, duration_ms)
        except Exception as e:
            duration_ms = int((_time.time() - _start) * 1000)
            self._log_cycle("login_anomaly_check", 0, 1, duration_ms, error_message=str(e))
            logger.error("login_anomaly_check failed: %s", e)

    def _creed_governance_reporter(self):
        """Job: Forward governance_audit_log events to standalone C.R.E.E.D. instance.

        Runs every 5 minutes. Tracks last-reported event ID in settings table.
        Maps platform event categories to C.R.E.E.D. compliance categories.
        """
        import requests as req

        CREED_URL = os.environ.get("CREED_API_URL", "http://192.168.1.200:8086")
        CATEGORY_MAP = {
            "creed_gate": "accountability",
            "bridge_dispatch": "transparency",
            "emotional": "fairness",
            "autonomous_operations": "safety",
            "system": "safety",
            "development": "transparency",
            "operations": "accountability",
            "data_management": "privacy",
            # Extended mappings — previously fell through to default "accountability"
            "telegram_send": "transparency",  # outbound comms logged (4,110+ events)
            "workload_balance": "fairness",  # K.I.N. load / rest decisions (1,512+ events)
            "welfare_ethics": "fairness",  # agent welfare gate events (162+ events)
            "node_planning": "accountability",  # fleet node lifecycle (259+ events)
            "orchestration": "transparency",  # dispatch pipeline steps (37+ events)
            "agent_management": "accountability",  # agent CRUD / lifecycle (19+ events)
            "autonomy": "safety",  # autonomous action gates (3+ events)
            "agent_lifecycle": "accountability",  # shift-state / decommission events
            "prompt_safety": "safety",  # T3253: jailbreak / prompt injection events
            "response_safety": "safety",  # T3252: uncertainty / hallucination rate events
        }
        SEVERITY_MAP = {
            "success": "info",
            "created": "info",
            "failed": "warning",
            "denied": "violation",
            "blocked": "violation",
            "error": "critical",
        }

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get last reported event ID
            cur.execute("SELECT value FROM system_config WHERE key = 'creed_reporter_last_id'")
            row = cur.fetchone()
            last_id = int(row["value"]) if row else 0

            # Fetch new events (batch of 100)
            cur.execute(
                """SELECT g.id, g.event_type, g.event_category, g.action,
                          g.agent_id, g.outcome, g.reason, g.timestamp,
                          a.name as agent_name
                   FROM governance_audit_log g
                   LEFT JOIN agents a ON g.agent_id = a.id
                   WHERE g.id > %s
                   ORDER BY g.id ASC LIMIT 100""",
                (last_id,),
            )
            events = cur.fetchall()

            if not events:
                conn.close()
                return

            reported = 0
            new_last_id = last_id

            for event in events:
                creed_category = CATEGORY_MAP.get(event["event_category"], "accountability")
                creed_severity = SEVERITY_MAP.get(event.get("outcome", ""), "info")
                payload = {
                    "event_type": event["event_type"] or "agent_action",
                    "source_platform": "archie",
                    "agent_id": str(event.get("agent_id") or "system"),
                    "agent_name": event.get("agent_name") or "System",
                    "category": creed_category,
                    "severity": creed_severity,
                    "description": (f"{event['action']}: {event.get('reason') or event['event_type']}"),
                    "metadata": {
                        "original_category": event["event_category"],
                        "original_outcome": event.get("outcome"),
                        "archie_event_id": event["id"],
                    },
                }

                try:
                    # #3958: per-agent tenant routing — each event authenticates
                    # with the EMITTING agent's product key (cached resolve via
                    # creed_emit; falls back to default tenant -> legacy key).
                    try:
                        import sys as _sys

                        if "/mnt/archie_brain/platform_v2" not in _sys.path:
                            _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                        from services.creed_emit import key_for_tenant, resolve_tenant

                        _creed_key, _ = key_for_tenant(
                            resolve_tenant(
                                agent_id=event.get("agent_id"),
                                agent_name=event.get("agent_name"),
                            )
                        )
                    except Exception:
                        _creed_key = os.environ.get("CREED_INGEST_KEY", "")
                    resp = req.post(
                        f"{CREED_URL}/api/v1/events",
                        json=payload,
                        headers=({"Authorization": f"Bearer {_creed_key}"} if _creed_key else {}),
                        timeout=5,
                    )
                    if resp.status_code == 201:
                        reported += 1
                        new_last_id = event["id"]
                    else:
                        logger.warning(
                            "[CREED Reporter] Event %d rejected: %s",
                            event["id"],
                            resp.text[:200],
                        )
                except req.RequestException as e:
                    logger.warning("[CREED Reporter] Connection failed: %s", e)
                    break

            # Save checkpoint
            if new_last_id > last_id:
                cur.execute(
                    """INSERT INTO system_config (key, value, description)
                       VALUES ('creed_reporter_last_id', %s, 'Last governance_audit_log ID forwarded to C.R.E.E.D. standalone')
                       ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
                    (str(new_last_id), str(new_last_id)),
                )
                conn.commit()

            # ── T3247: Pillar score-drop Telegram alert ──────────────────────
            if reported > 0:
                try:
                    score_resp = req.get(f"{CREED_URL}/api/v1/scores", timeout=5)
                    if score_resp.status_code == 200:
                        scores_now = score_resp.json()
                        overall_now = float(scores_now.get("overall", 100))
                        cur.execute("SELECT value FROM system_config " "WHERE key = 'creed_score_prev_overall'")
                        prev_row = cur.fetchone()
                        prev_score = float(prev_row["value"]) if prev_row else None
                        cur.execute(
                            """INSERT INTO system_config (key, value, description)
                               VALUES ('creed_score_prev_overall', %s,
                                       'Prev C.R.E.E.D. overall score for drop-alert baseline')
                               ON CONFLICT (key) DO UPDATE
                               SET value = %s, updated_at = NOW()""",
                            (str(round(overall_now, 2)), str(round(overall_now, 2))),
                        )
                        conn.commit()
                        if prev_score is not None and (prev_score - overall_now) >= 5.0:
                            drop = round(prev_score - overall_now, 1)
                            grade = scores_now.get("grade", "?")
                            by_cat = scores_now.get("by_category", {})

                            def _pv(v):
                                return v.get("score", v) if isinstance(v, dict) else v

                            pillar_lines = "\n".join(
                                f"  {cat}: {round(float(_pv(v)), 1)}%" for cat, v in by_cat.items()
                            )
                            alert_msg = (
                                f"⚠️ C.R.E.E.D. score dropped {drop} pts\n"
                                f"Overall: {round(overall_now, 1)}% (Grade {grade})\n"
                                f"Previous: {round(prev_score, 1)}%\n\n"
                                f"Pillars:\n{pillar_lines}"
                            )
                            try:
                                _ppath = os.path.join(os.path.dirname(__file__), "..", "platform_v2")
                                if _ppath not in sys.path:
                                    sys.path.insert(0, _ppath)
                                from services.director_report_service import (
                                    submit_via_inbox,
                                )

                                submit_via_inbox(
                                    category="creed_alert",
                                    title=f"C.R.E.E.D. score alert — {drop}pt drop",
                                    message=alert_msg,
                                    severity="high",
                                )
                                logger.warning(
                                    "[CREED Reporter] Score drop alert sent: " "%.1f -> %.1f",
                                    prev_score,
                                    overall_now,
                                )
                            except Exception as _te:
                                logger.warning("[CREED Reporter] Telegram alert failed: %s", _te)
                except Exception as _se:
                    logger.debug("[CREED Reporter] Score-drop check failed: %s", _se)

            conn.close()

            if reported > 0:
                logger.info(
                    "[CREED Reporter] Forwarded %d events (up to id %d)",
                    reported,
                    new_last_id,
                )

        except Exception as e:
            logger.error("[CREED Reporter] Job failed: %s", e)

    def _email_morning_digest(self):
        """Job #76: Email HQ daily digest → Telegram. Runs every 15 min and self-gates
        on the tunable send time (mailhq:digest:time, ET) so the schedule is adjustable
        from Mail HQ with no redeploy; sends at most once per day (T3288 + Slice 5)."""
        try:
            from tools.email_manager import mailhq_settings

            if not mailhq_settings.digest_due():
                return

            from services.telegram_service import send_info
            from tools.email_manager.digest_service import build_morning_digest

            title, message = build_morning_digest()
            send_info(title, message)
            mailhq_settings.mark_digest_sent()
            logger.info("[Email Digest] Daily digest sent: %s", title)
        except Exception as e:
            logger.error("[Email Digest] Job failed: %s", e)


# ---------------------------------------------------------------------------
# Job #47 — Chat Memory Extraction (module-level, no app context needed)
# ---------------------------------------------------------------------------


def _process_chat_memories():
    """Job #47: Extract conversation summaries and pinned memories from idle chats."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find conversations idle for 5+ minutes with unsummarized messages
        cur.execute(
            """
            SELECT dc.id, dc.agent_id, dc.user_id, dc.last_message_at
            FROM directory_conversations dc
            WHERE dc.last_message_at IS NOT NULL
              AND dc.last_message_at < NOW() - INTERVAL '5 minutes'
              AND dc.last_message_at > COALESCE(
                (SELECT MAX(created_at) FROM directory_agent_memories
                 WHERE agent_id = dc.agent_id AND user_id = dc.user_id
                   AND memory_type = 'summary'),
                '1970-01-01'
              )
        """
        )
        idle_convos = cur.fetchall()

        for convo in idle_convos:
            try:
                _summarize_conversation(cur, conn, convo)
            except Exception as e:
                logging.error(f"Chat memory extraction failed for conv {convo['id']}: {e}")

        conn.close()
    except Exception as e:
        logging.error(f"Job #47 chat memories error: {e}")


def _summarize_conversation(cur, conn, convo):
    """Summarize a single conversation and extract pinned memories."""
    # Get messages since last summary
    cur.execute(
        """
        SELECT sender_type, message, timestamp
        FROM directory_messages
        WHERE conversation_id = %s
        ORDER BY timestamp ASC
    """,
        (convo["id"],),
    )
    messages = cur.fetchall()

    if len(messages) < 2:
        return  # Not enough to summarize

    # Get agent info
    cur.execute("SELECT name, display_name, title FROM agents WHERE id = %s", (convo["agent_id"],))
    agent = cur.fetchone()
    if not agent:
        return
    agent_name = agent.get("display_name") or agent.get("name")

    # Build conversation text
    conv_text = ""
    for msg in messages:
        role = "User" if msg["sender_type"] == "user" else agent_name
        conv_text += f"{role}: {msg['message']}\n"

    # Dispatch summarization via canonical module-level dispatch() — the
    # previous .dispatch() call on the instance silently AttributeError'd.
    from tools.department_hq.services.department_dispatcher import dispatch

    # Summary
    summary_result = dispatch(
        capability="summarize",
        prompt=f"Summarize this conversation in 2-3 sentences:\n\n{conv_text}",
        module_id="directory_memory",
        system_prompt="You are a helpful assistant. Provide a concise summary.",
        prefer_agent=agent.get("name"),
    )
    summary = (
        summary_result.response.strip() if summary_result and summary_result.success and summary_result.response else ""
    )

    if summary:
        cur.execute(
            """
            INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
            VALUES (%s, %s, 'summary', %s)
        """,
            (convo["agent_id"], convo["user_id"], summary),
        )

    # Pinned memories
    pinned_result = dispatch(
        capability="summarize",
        prompt=f"What important facts should you remember about this user from this conversation? List each fact on its own line. Only include facts worth remembering for future conversations.\n\n{conv_text}",
        module_id="directory_memory",
        system_prompt="You are a helpful assistant. Extract key facts about the user.",
        prefer_agent=agent.get("name"),
    )
    pinned_text = (
        pinned_result.response.strip() if pinned_result and pinned_result.success and pinned_result.response else ""
    )

    if pinned_text:
        for line in pinned_text.split("\n"):
            line = line.strip().lstrip("•-* ")
            if line and len(line) > 10:
                cur.execute(
                    """
                    INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
                    VALUES (%s, %s, 'pinned', %s)
                """,
                    (convo["agent_id"], convo["user_id"], line),
                )

    conn.commit()
