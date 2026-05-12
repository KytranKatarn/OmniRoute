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
from typing import Any, Dict, List, Optional

import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from db import get_db

# Allow importing platform_v2 services from ai_bridge context
if "/mnt/archie_brain/platform_v2" not in sys.path:
    sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from services.time_utils import now_local_str
from services.agent_service import (
    add_skill,
    recover_idle,
    update_welfare,
)

logger = logging.getLogger("agent_loop")


def log_governance_event(event_type, action, outcome, details=None, event_category='system', agent_id=None):
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


def _send_approval_telegram(
    approval_id: int, action_type: str, action_data: dict, reason: str
):
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
            text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=_re.DOTALL)
            text = _re.sub(r'__(.+?)__', r'\1', text, flags=_re.DOTALL)
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
        elif action_data:
            for k, v in list(action_data.items())[:3]:
                lines.append(f"{k}: {v}")

        submit_via_inbox(
            category="approval_request",
            title=f"Approval Required \u2014 {action_type} #{approval_id}",
            message="\n".join(lines),
            source_agent="A.R.C.H.I.E.",
            severity="critical",
            department="Executive Office",
        )
        logger.info(
            "Approval #%s submitted to director_reports inbox (category=approval_request)",
            approval_id,
        )
    except Exception as exc:
        logger.error("Failed to submit approval #%s to inbox: %s", approval_id, exc)
def _validate_approval_request(
    action_type: str, action_data: dict
) -> Optional[str]:
    """Validate approval request inputs. Returns error message or None if valid."""
    if not action_type or not isinstance(action_type, str):
        return "action_type must be a non-empty string"
    if not isinstance(action_data, dict):
        return "action_data must be a dict"
    return None


def _check_existing_approval(
    action_type: str, action_data: dict, cur
) -> bool:
    """Check if a pending approval that would collide with this request already exists.

    Dedup key depends on the action_type:

      - ``contractor_dispatch`` uses ``(action_type, agent, capability)`` so
        two parallel contractor runs for different agents / capabilities
        can be in flight at the same time without blocking each other.
        Phase 7 smoke testing discovered that a coarse action_type-only
        dedup was blocking every new contractor approval whenever one
        was already pending. Fall back to the coarse check if the JSON
        fields are missing so we never bypass dedup entirely.

      - All other action_types keep the original coarse check — one
        pending approval per action_type at a time.
    """
    if action_type == "contractor_dispatch":
        agent = (action_data or {}).get("agent")
        capability = (action_data or {}).get("capability")
        if agent:
            cur.execute(
                """
                SELECT id FROM autonomy_approval_queue
                WHERE action_type = %s
                  AND status = 'pending'
                  AND action_data->>'agent' = %s
                  AND (action_data->>'capability') IS NOT DISTINCT FROM %s
                LIMIT 1
                """,
                (action_type, agent, capability),
            )
            return cur.fetchone() is not None

    cur.execute(
        "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' LIMIT 1",
        (action_type,),
    )
    return cur.fetchone() is not None


def _get_effective_tier(action_type: str, tier: int, cur) -> int:
    """Determine effective tier by checking tier-1 auto-approve config."""
    cur.execute(
        "SELECT config_value FROM autonomy_config WHERE config_key = 'tier1_auto_approve'"
    )
    row = cur.fetchone()
    tier1_types = row["config_value"].get("types", []) if row else []
    return 1 if action_type in tier1_types else tier


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

    cur.execute(
        f"""
        INSERT INTO autonomy_approval_queue
        (action_type, action_data, tier, status, priority, requested_by, reason,
         approved_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s,
                {'NOW()' if effective_tier == 1 else 'NULL'},
                NOW() + INTERVAL '24 hours')
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
    "media_hub_health_check": "Operations & Infrastructure",
    "media_queue_cleanup": "Creative & Design",
    "media_export_cleanup": "Creative & Design",
    "market_watch_cycle": "Analytics & Intelligence",
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
        )

        self.scheduler.add_job(
            with_app_context(self._process_scheduled_tasks),
            trigger=IntervalTrigger(seconds=30),
            id="agent_scheduled_tasks",
            name="Agent Loop: Scheduled Tasks",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_reminders),
            trigger=IntervalTrigger(seconds=30),
            id="agent_reminders",
            name="Agent Loop: Reminders",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_approval_queue),
            trigger=IntervalTrigger(seconds=60),
            id="agent_approvals",
            name="Agent Loop: Approval Queue",
            replace_existing=True,
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
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._forward_notifications_to_telegram),
            trigger=IntervalTrigger(seconds=15),
            id="agent_telegram_notify",
            name="Agent Loop: Telegram Notifications",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._process_browser_tasks),
            trigger=IntervalTrigger(minutes=5),
            id="agent_browser_tasks",
            name="Agent Loop: Browser Tasks",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._generate_briefings),
            trigger=IntervalTrigger(minutes=5),
            id="agent_briefings",
            name="Agent Loop: Briefings",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_anomalies),
            trigger=IntervalTrigger(minutes=5),
            id="agent_anomaly_detection",
            name="Agent Loop: Anomaly Detection",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._generate_reports),
            trigger=IntervalTrigger(minutes=15),
            id="agent_reports",
            name="Agent Loop: Scheduled Reports",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._notify_email_telegram),
            trigger=IntervalTrigger(seconds=30),
            id="agent_email_telegram_notify",
            name="Agent Loop: Email Telegram Notifications",
            replace_existing=True,
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
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._reap_stuck_jobs),
            trigger=IntervalTrigger(minutes=5),
            id="agent_stuck_job_watchdog",
            name="Agent Loop: Stuck Job Watchdog",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._platform_watchdog),
            trigger=IntervalTrigger(minutes=2),
            id="platform_watchdog",
            name="Agent Loop: Platform Watchdog (load/mem/swap)",
            replace_existing=True,
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
        )

        self.scheduler.add_job(
            with_app_context(self._comfyui_idle_stop),
            trigger=IntervalTrigger(minutes=5),
            id="comfyui_idle_stop",
            name="Agent Loop: ComfyUI Idle Stop (30min)",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_qa_scheduled),
            trigger=IntervalTrigger(hours=6),
            id="qa_scheduled_run",
            name="Agent Loop: P.R.O.B.E. QA Scheduled Run",
            replace_existing=True,
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
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_warden_backup_verify),
            trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
            id="warden_backup_verify",
            name="W.A.R.D.E.N.: Daily Backup Integrity Check",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_warden_compliance_check),
            trigger=CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="America/Toronto"),
            id="warden_compliance_check",
            name="W.A.R.D.E.N.: Weekly Admin Compliance Scan",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_proactive_scan),
            trigger=IntervalTrigger(hours=6),
            id="agent_proactive_scan",
            name="Agent Loop: Proactive Code Scan",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_dependency_audit),
            trigger=IntervalTrigger(hours=6, start_date="2026-01-01 03:30:00"),
            id="dependency_audit",
            name="Agent Loop: Dependency CVE Audit",
            replace_existing=True,
        )

        # S.P.E.C.T.R.A. — nightly dispatch misroute audit (Project #272 / Task #2105).
        # 02:15 UTC offset from the other nightly maintenance windows.
        self.scheduler.add_job(
            with_app_context(self._run_misroute_audit),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 02:15:00"),
            id="spectra_misroute_audit",
            name="Agent Loop: S.P.E.C.T.R.A. Dispatch Misroute Audit",
            replace_existing=True,
        )

        # S.P.E.C.T.R.A. → Audit Pipeline adapter (Project #272 / Task #2186).
        # 02:30 UTC — 15 min after the audit, so findings are fresh.
        self.scheduler.add_job(
            with_app_context(self._run_misroute_to_proposal_adapter),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 02:30:00"),
            id="misroute_to_proposal_adapter",
            name="Agent Loop: S.P.E.C.T.R.A. Misroute → Proposal Adapter",
            replace_existing=True,
        )

        # Archie-as-delegate worker (Project #276 / Task #2209).
        # Polls unified_tasks for pending delegated work every 30s.
        # Fast cadence so Claude → Archie feels interactive, not batch.
        self.scheduler.add_job(
            with_app_context(self._run_delegate_task_worker),
            trigger=IntervalTrigger(seconds=30),
            id="delegate_task_worker",
            name="Agent Loop: Archie Delegate Task Worker",
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
            replace_existing=True,
            max_instances=1,
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
        )

        # F.O.R.G.E. — daily dep drift audit (Project #272 Phase 2 / Task #2109).
        # 03:15 UTC — after S.P.E.C.T.R.A. and K.I.N. digest windows.
        self.scheduler.add_job(
            with_app_context(self._run_dep_drift_audit),
            trigger=IntervalTrigger(hours=24, start_date="2026-01-01 03:15:00"),
            id="forge_dep_drift",
            name="Agent Loop: F.O.R.G.E. Dependency Drift Audit",
            replace_existing=True,
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

        # F.O.R.G.E. AI diff analysis — processes up to 3 pending PR reviews every 10 min.
        self.scheduler.add_job(
            with_app_context(self._run_pr_diff_analysis),
            trigger=IntervalTrigger(minutes=10),
            id="forge_pr_diff_analysis",
            name="Agent Loop: F.O.R.G.E. PR Diff Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Email IMAP sync — polls provisioned mailboxes every 5 min.
        self.scheduler.add_job(
            with_app_context(self._run_email_imap_sync),
            trigger=IntervalTrigger(minutes=5),
            id="email_imap_sync",
            name="Agent Loop: Email HQ IMAP Sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # Daily repo health check — README/description/topics/license for each tracked repo.
        self.scheduler.add_job(
            with_app_context(self._run_repo_health_check),
            "cron",
            hour=6,
            minute=0,
            id="forge_repo_health_check",
            name="Agent Loop: F.O.R.G.E. Repo Health Check",
            replace_existing=True,
            max_instances=1,
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

        # C.O.D.E.X. — event auto-documentation (Project #272 Phase 2 / Task #2108).
        # Runs every 30 min; template-based, no LLM. Scans project_decisions
        # for undocumented rows and writes a vault_note per ADR.
        self.scheduler.add_job(
            with_app_context(self._run_codex_event_docs),
            trigger=IntervalTrigger(minutes=30),
            id="codex_event_docs",
            name="Agent Loop: C.O.D.E.X. Event Auto-Documentation",
            replace_existing=True,
        )

        # V.I.G.I.L. — infra heartbeat (Project #272 Phase 2 / Task #2127).
        # Every 5 min — critical containers going absent must be caught fast.
        # Triggered by the 2026-04-18 NPM removal outage (KB mistake #256963).
        self.scheduler.add_job(
            with_app_context(self._run_infra_heartbeat),
            trigger=IntervalTrigger(minutes=5),
            id="vigil_infra_heartbeat",
            name="Agent Loop: V.I.G.I.L. Infrastructure Heartbeat",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_ddns),
            trigger=IntervalTrigger(minutes=15),
            id="ddns_ip_monitor",
            name="Agent Loop: DDNS Public IP Monitor",
            replace_existing=True,
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
            replace_existing=True,
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
        )

        self.scheduler.add_job(
            with_app_context(self._media_generation_worker),
            trigger=IntervalTrigger(seconds=30),
            id="media_generation_worker",
            name="Agent Loop: Media Generation Worker (Creative & Design / M.U.S.E.)",
            max_instances=1,
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._portrait_refinement_worker),
            trigger=IntervalTrigger(seconds=30),
            id="portrait_refinement_worker",
            name="Agent Loop: Portrait Refinement Worker (Creative & Design / M.U.S.E.)",
            max_instances=1,
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._model_dispatch_worker),
            trigger=IntervalTrigger(seconds=15),
            id="model_dispatch_worker",
            name="Agent Loop: Model-Affinity Dispatch Queue Worker (Department HQ)",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

        from apscheduler.triggers.cron import CronTrigger as _CronTrigger

        self.scheduler.add_job(
            with_app_context(self._website_deploy_worker),
            trigger=_CronTrigger(hour=3, minute=0, timezone="America/Toronto"),
            id="website_deploy_worker",
            name="Agent Loop: Website Deploy (Operations / B.A.S.E.)",
            max_instances=1,
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._compute_media_analytics),
            trigger=IntervalTrigger(hours=1),
            id="media_analytics_snapshot",
            name="Agent Loop: Media Analytics Snapshot",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._process_agent_emails),
            trigger=IntervalTrigger(minutes=5),
            id="agent_email_processing",
            name="Agent Loop: Gmail Processing",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._process_world_events),
            trigger=IntervalTrigger(seconds=30),
            id="game_world_event_processor",
            name="Agent Loop: Game World Events",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._update_market_prices),
            trigger=IntervalTrigger(minutes=5),
            id="game_market_price_update",
            name="Agent Loop: Game Market Prices",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._agent_calendar_drive_tasks),
            trigger=IntervalTrigger(minutes=15),
            id="agent_calendar_drive",
            name="Agent Loop: Calendar + Drive Autonomy",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._update_stock_prices),
            trigger=IntervalTrigger(minutes=5),
            id="stock_price_updater",
            name="Agent Loop: Stock Price Updater",
            replace_existing=True,
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
        )
        self.scheduler.add_job(
            with_app_context(self._track_git_changes),
            trigger=IntervalTrigger(minutes=30),
            id="git_change_tracker",
            name="Agent Loop: Git Change Tracker",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._monitor_ssh_logins),
            trigger=IntervalTrigger(minutes=5),
            id="agent_ssh_monitor",
            name="Agent Loop: SSH Login Monitor",
            replace_existing=True,
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
            replace_existing=True,
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
            replace_existing=True,
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
            replace_existing=True,
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
        )

        # Auto log ingestion (every 30 min)
        self.scheduler.add_job(
            with_app_context(self._auto_log_ingestion),
            trigger=IntervalTrigger(minutes=30),
            id="agent_auto_log_ingestion",
            name="Agent Loop: Auto Log Ingestion",
            replace_existing=True,
        )

        # Weekly dependency scan (Sunday 4 AM)
        self.scheduler.add_job(
            with_app_context(self._weekly_dependency_scan),
            trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="America/Toronto"),
            id="agent_weekly_dependency_scan",
            name="Agent Loop: Weekly Dependency Scan",
            replace_existing=True,
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
            replace_existing=True,
        )

        # Ollama model health (every 30 min)
        self.scheduler.add_job(
            with_app_context(self._ollama_model_health),
            trigger=IntervalTrigger(minutes=30),
            id="agent_ollama_model_health",
            name="Agent Loop: Ollama Model Health",
            replace_existing=True,
        )

        # Ollama placement telemetry (every 5 min)
        self.scheduler.add_job(
            with_app_context(self._ollama_placement_telemetry),
            trigger=IntervalTrigger(minutes=5),
            id="ollama_placement_telemetry",
            name="Agent Loop: Ollama Placement Telemetry",
            replace_existing=True,
            max_instances=1,
        )

        # Media Hub health check (every 10 min) — probes Plex/Jellyfin/Sonarr/…
        self.scheduler.add_job(
            with_app_context(self._media_hub_health_check),
            trigger=IntervalTrigger(minutes=10),
            id="agent_media_hub_health_check",
            name="Agent Loop: Media Hub Service Health",
            replace_existing=True,
        )

        # Media queue cleanup (every 1h)
        self.scheduler.add_job(
            with_app_context(self._media_queue_cleanup),
            trigger=IntervalTrigger(hours=1),
            id="agent_media_queue_cleanup",
            name="Agent Loop: Media Queue Cleanup",
            misfire_grace_time=300,
            replace_existing=True,
        )

        # Media export cleanup (every 1h)
        self.scheduler.add_job(
            with_app_context(self._media_export_cleanup),
            trigger=IntervalTrigger(hours=1),
            id="agent_media_export_cleanup",
            name="Agent Loop: Media Export Cleanup",
            misfire_grace_time=300,
            replace_existing=True,
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
        )

        # Job #63: Social video auto-approve (every 15 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_auto_approve),
            "interval",
            minutes=15,
            id="social_video_auto_approve",
            name="Social Video: Auto-Approve",
            replace_existing=True,
        )

        # Job #64: Social video publish scheduled items (every 5 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_publish),
            "interval",
            minutes=5,
            id="social_video_publish",
            name="Social Video: Publish Scheduled",
            replace_existing=True,
        )

        # Job #65: AutoShorts slideshow render (every 2 minutes)
        self.scheduler.add_job(
            with_app_context(self._social_video_slideshow_render),
            "interval",
            minutes=2,
            id="social_video_slideshow_render",
            name="Social Video: Slideshow Renderer",
            replace_existing=True,
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
        )

        # ── V.I.G.I.L. Security & Compliance Department Jobs ──

        self.scheduler.add_job(
            with_app_context(self._vigilil_network_health),
            trigger=IntervalTrigger(seconds=60),
            id="vigilil_network_health",
            name="V.I.G.I.L.: Network Health Monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_traffic_aggregator),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_traffic_aggregator",
            name="V.I.G.I.L.: Traffic Aggregator",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_nagios_sync),
            trigger=IntervalTrigger(minutes=2),
            id="vigilil_nagios_sync",
            name="V.I.G.I.L.: Nagios Sync",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_device_watcher),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_device_watcher",
            name="V.I.G.I.L.: Device Watcher",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_dns_anomaly),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_dns_anomaly",
            name="V.I.G.I.L.: DNS Anomaly Detector",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_log_health),
            trigger=IntervalTrigger(minutes=15),
            id="vigilil_log_health",
            name="V.I.G.I.L.: Log Health Monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_daily_report),
            trigger=CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
            id="vigilil_daily_report",
            name="V.I.G.I.L.: Daily Bandwidth Reporter",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_threat_responder),
            trigger=IntervalTrigger(seconds=30),
            id="vigilil_threat_responder",
            name="V.I.G.I.L.: Threat Responder",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_vpn_scan),
            trigger=IntervalTrigger(minutes=5),
            id="vigilil_vpn_scan",
            name="V.I.G.I.L.: VPN Usage Monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._vigilil_bandwidth_alerts),
            trigger=IntervalTrigger(minutes=30),
            id="vigilil_bandwidth_alerts",
            name="V.I.G.I.L.: Bandwidth Threshold Monitor",
            replace_existing=True,
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
            replace_existing=True,
        )
        logger.info("Registered job: Knowledge Quality Review (every 30m)")

        # Job: C.R.E.E.D. Governance Reporter (every 5 min)
        self.scheduler.add_job(
            with_app_context(self._creed_governance_reporter),
            trigger=IntervalTrigger(minutes=5),
            id="creed_governance_reporter",
            name="C.R.E.E.D. Governance Reporter",
            replace_existing=True,
        )
        logger.info("Registered job: C.R.E.E.D. Governance Reporter (every 5m)")

        self._running = True
        logger.info("Agent loop started with 73 jobs")

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
                agent_name = row[0] if not hasattr(row, 'get') else row['agent_name']
                cron_expr = row[2] if not hasattr(row, 'get') else row['schedule_cron']
                last_gen = row[3] if not hasattr(row, 'get') else row['last_generated_at']
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
                    logger.error(
                        "Agent media schedule error for %s: %s", agent_name, e
                    )
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
        try:
            from services.department_coordinator import get_coordinator as _get_coord
            coord = _get_coord()
            agent = coord.select_agent("image_generation", "Creative & Design")
            if agent:
                logger.info("media_generation_worker: %s (id=%s) selected via DHQ for image_generation", agent.get("name", "?"), agent.get("id", "?"))
            else:
                logger.warning("media_generation_worker: DHQ found no image_generation agent — proceeding anyway")
        except Exception as dhq_err:
            logger.warning("media_generation_worker: DHQ agent lookup failed (non-blocking): %s", dhq_err)

        # Step 2: P.I.X.E.L.'s tool is ComfyUI — warm it up before claiming work.
        try:
            from ai_bridge.comfyui_service import get_comfyui_service
            svc = get_comfyui_service()
            if svc.is_stopped():
                logger.info("media_generation_worker: ComfyUI stopped — P.I.X.E.L. warming up container")
                healthy = svc.wake_if_stopped()
                if not healthy:
                    logger.warning("media_generation_worker: ComfyUI warmboot failed — leaving jobs pending for next tick")
                    return
                logger.info("media_generation_worker: ComfyUI healthy after warmboot")
        except Exception as wake_err:
            logger.warning("media_generation_worker: ComfyUI warmboot check failed: %s", wake_err)

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE media_generation_queue
                    SET status = 'dispatched', started_at = NOW()
                    WHERE id IN (
                        SELECT id FROM media_generation_queue
                        WHERE status = 'pending'
                          AND (params->>'provider' = 'comfyui' OR params->>'provider' IS NULL)
                        ORDER BY created_at ASC
                        LIMIT 1
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
                try:
                    from tools.media_studio.services.generation_service import (
                        generate_via_comfyui,
                        generate_video_via_comfyui,
                        generate_audio,
                    )

                    if media_type == "video":
                        generate_video_via_comfyui(queue_id)
                    elif media_type == "audio":
                        generate_audio(queue_id)
                    else:
                        generate_via_comfyui(queue_id)
                except Exception as e:
                    err_str = str(e)
                    # ComfyUI down = transient — reset to pending so next tick retries.
                    # Permanent errors (bad prompt, missing model) = fail immediately.
                    is_transient = "unavailable" in err_str.lower() or "connection" in err_str.lower() or "timeout" in err_str.lower()
                    if is_transient:
                        logger.warning("media_generation_worker: queue %s — ComfyUI unavailable, resetting to pending: %s", queue_id, err_str)
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
        except Exception as e:
            logger.error("media_generation_worker error: %s", e)

    def _website_deploy_worker(self):
        """Daily full-site deploy to Hostinger for all public websites.

        Operations & Infrastructure — B.A.S.E. Director. Runs daily at 03:00.
        Deploys kytranempowerment.com and creed-ai.org in sequence.
        Records last_run + last_status in system_config per domain.
        Also triggerable manually via Repair Bay → Ship → Website tab.
        """
        from database import get_db_cursor
        from services.deploy_service import run_deploy_pipeline
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
            try:
                result = run_deploy_pipeline(
                    "deploy_static",
                    {
                        "domain": domain,
                        "source_path": site["source"],
                        "verify_url": site["verify_url"],
                        "changed_files": ["assets/portraits/", "data/"],
                    },
                )
                status = "success" if result.success else "failed"
                if not result.success:
                    logger.error("[WebsiteDeploy] %s failed: %s", domain, result.error)
            except Exception as exc:
                logger.exception("[WebsiteDeploy] %s error: %s", domain, exc)
                status = "failed"

            ts = datetime.datetime.now(timezone.utc).isoformat()
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    for k, v in [(key_ts, ts), (key_st, status)]:
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
                            agent_id, round_num, feedback,
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
            count = compute_snapshot(period_type='hourly')
            logger.info(f"[Analytics] Hourly: {count} snapshots")
            if datetime.now(timezone.utc).hour == 0:
                daily_count = compute_snapshot(period_type='daily')
                logger.info(f"[Analytics] Daily: {daily_count} snapshots")
        except Exception as e:
            logger.error(f"[Analytics] Snapshot failed: {e}")

    def _process_agent_emails(self):
        """Process inboxes for all agent Gmail accounts."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT id FROM google_accounts WHERE owner_type = 'agent'"
                )
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
                    logger.warning(
                        f"Agent email processing failed for account {acc['id']}: {e}"
                    )
        except Exception as e:
            logger.error(f"Agent email job failed: {e}")

    def _agent_calendar_drive_tasks(self):
        """Auto-schedule calendar events from tasks for all agent Google accounts."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT id, owner_id FROM google_accounts WHERE owner_type = 'agent'"
                )
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
                    logger.warning(
                        f"Agent calendar task failed for account {acc['id']}: {e}"
                    )

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
                ['git', 'log', '--oneline', '-5', '--format=%h %s (%ar)'],
                cwd='/mnt/archie_brain',
                capture_output=True, text=True, timeout=10
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
                        (recent, Json(['git', 'commits', 'version-control', 'auto-generated'])),
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
                            "next_run": (
                                str(job.next_run_time) if job.next_run_time else None
                            ),
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
                cur.execute(
                    "SELECT * FROM email_settings WHERE is_default = true AND is_active = true"
                )
                smtp_settings = cur.fetchone()

                if not smtp_settings:
                    logger.warning(
                        "Agent loop: No GWS account or SMTP settings, skipping email queue"
                    )
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
                            subject = (
                                subject.replace(f"{{{{{key}}}}}", str(val))
                                if subject
                                else subject
                            )
                            body_html = (
                                body_html.replace(f"{{{{{key}}}}}", str(val))
                                if body_html
                                else body_html
                            )

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
                        self._send_smtp(
                            smtp_settings, email["recipient"], subject, body_html
                        )

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
            logger.info(
                f"Email queue: {processed} sent, {failed} failed ({duration_ms}ms)"
            )

    def _send_smtp(
        self, smtp_settings: dict, recipient: str, subject: str, body_html: str
    ):
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
                    logger.error(
                        f"Failed to execute scheduled task #{task['id']} ({task['name']}): {e}"
                    )
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
            logger.info(
                f"Scheduled tasks: {processed} executed, {failed} failed ({duration_ms}ms)"
            )

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
            logger.warning(
                f"Unknown scheduled task type: {task_type} (task #{task['id']})"
            )

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
            logger.info(
                f"Reminders: {processed} notified, {failed} failed ({duration_ms}ms)"
            )

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
                logger.info(
                    f"Email inbox: {fetched} fetched, {analyzed} analyzed ({duration_ms}ms)"
                )

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
            cur.execute("""
                SELECT id FROM email_inbox
                WHERE ai_analyzed_at IS NULL AND is_archived = FALSE
                ORDER BY received_at DESC LIMIT 3
            """)
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
            cur.execute("""
                SELECT id FROM browser_tasks
                WHERE status = 'pending'
                  AND (next_run_at IS NULL OR next_run_at <= NOW())
                ORDER BY priority ASC, created_at ASC
                LIMIT 5
                """)
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
            logger.info(
                f"Browser tasks: {processed} completed, {failed} failed ({duration_ms}ms)"
            )

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
            cur.execute("""
                SELECT tu.telegram_id, tu.id as tg_user_id,
                       COALESCE(tep.notify_urgent, TRUE) as notify_urgent,
                       COALESCE(tep.notify_action_required, TRUE) as notify_action_required,
                       COALESCE(tep.digest_enabled, TRUE) as digest_enabled,
                       COALESCE(tep.digest_interval_minutes, 60) as digest_interval,
                       tep.last_digest_at
                FROM telegram_users tu
                LEFT JOIN telegram_email_prefs tep ON tu.id = tep.telegram_user_id
                WHERE tu.is_authorized = TRUE
            """)
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
                        self._send_email_telegram_notification(
                            gateway, user["telegram_id"], email
                        )
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

                    cur.execute("""
                        SELECT id, from_name, from_address, subject, ai_category, ai_summary
                        FROM email_inbox
                        WHERE ai_analyzed_at IS NOT NULL
                        AND telegram_notified_at IS NULL
                        AND ai_category NOT IN ('urgent', 'action_required')
                        AND is_archived = FALSE
                        ORDER BY received_at DESC LIMIT 20
                    """)
                    digest_emails = cur.fetchall()

                    if digest_emails:
                        self._send_email_telegram_digest(
                            gateway, user["telegram_id"], digest_emails
                        )
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
                        InlineKeyboardButton(
                            "Reply", callback_data=f"email_reply_{email['id']}"
                        ),
                        InlineKeyboardButton(
                            "Archive", callback_data=f"email_archive_{email['id']}"
                        ),
                        InlineKeyboardButton(
                            "Star", callback_data=f"email_star_{email['id']}"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "Mark Read", callback_data=f"email_read_{email['id']}"
                        ),
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
                gateway._application.bot.send_message(
                    chat_id=telegram_id, text=text, parse_mode="Markdown"
                ),
                loop,
            )
        except Exception as e:
            logger.error(f"Send email digest failed: {e}")

    # ------------------------------------------------------------------
    # Approval Queue Processor
    # ------------------------------------------------------------------

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
            cur.execute("""
                UPDATE autonomy_approval_queue
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'pending' AND expires_at < NOW()
                RETURNING id, action_type
                """)
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
            cur.execute("""
                SELECT id, action_type, action_data
                FROM autonomy_approval_queue
                WHERE status = 'rejected' AND action_type = 'media_generation'
                  AND updated_at > NOW() - INTERVAL '5 minutes'
                """)
            rejected_media = cur.fetchall()
            for item in rejected_media:
                try:
                    rdata = item["action_data"] if isinstance(item["action_data"], dict) else json.loads(item["action_data"])
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
            cur.execute("""
                SELECT id, action_type, action_data, tier, requested_by, reason
                FROM autonomy_approval_queue
                WHERE status = 'approved'
                ORDER BY priority ASC, created_at ASC
                LIMIT 10
                """)
            approved = cur.fetchall()

            for item in approved:
                try:
                    result = self._execute_approved_action(cur, conn, item)
                    cur.execute(
                        """
                        UPDATE autonomy_approval_queue
                        SET status = 'executed', executed_at = NOW(),
                            execution_result = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (json.dumps(result or {}), item["id"]),
                    )
                    conn.commit()
                    processed += 1

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
                        "success",
                        {"approval_id": item["id"], "result": result},
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to execute approved action #{item['id']}: {e}"
                    )
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

    def _execute_approved_action(self, cur, conn, item: dict) -> dict:
        """Execute an approved action from the approval queue."""
        action_type = item["action_type"]
        data = (
            item["action_data"]
            if isinstance(item["action_data"], dict)
            else json.loads(item["action_data"])
        )

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
                gen_params = queue_row["params"] if isinstance(queue_row["params"], dict) else json.loads(queue_row["params"] or "{}")
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
                from bridge_dispatcher import get_dispatcher

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
                from bridge_dispatcher import get_dispatcher
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
                    logger.info(
                        f"Agent {agent_id} reactivated from approval "
                        f"#{item['id']}: {result.get('name')}"
                    )
                    return {"executed": True, **result}
                return {
                    "executed": False,
                    "error": result.get("error", "reactivate_agent failed"),
                }
            except Exception as react_err:
                logger.error(f"Agent reactivation from approval failed: {react_err}")
                return {"executed": False, "error": str(react_err)}

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
                    logger.info(
                        f"Container {compose_service} restarted from approval "
                        f"#{item['id']}"
                    )
                    return {"executed": True, **result}
                return {
                    "executed": False,
                    "error": result.get("error", "restart_container failed"),
                }
            except Exception as restart_err:
                logger.error(
                    f"Container restart from approval failed: {restart_err}"
                )
                return {"executed": False, "error": str(restart_err)}

        elif action_type == "improvement_approve":
            # Approved improvement proposal — trigger auto-execution pipeline
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
                    import importlib

                    def _run_auto_execute():
                        try:
                            import sys

                            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                            from services.proposal_service import auto_run

                            auto_run(proposal_id)
                        except Exception as exec_err:
                            logger.error(
                                f"Auto-execution failed for proposal #{proposal_id}: {exec_err}"
                            )

                    thread = threading.Thread(target=_run_auto_execute, daemon=True)
                    thread.start()

                logger.info(
                    f"Improvement proposal #{proposal_id} approved via autonomy queue, "
                    f"auto-execution started"
                )
                return {"executed": True, "proposal_id": proposal_id}

            except Exception as imp_err:
                logger.error(f"Improvement approval execution failed: {imp_err}")
                return {"executed": False, "error": str(imp_err)}

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
                        proposal_id, gate["passed_count"], gate["total"]
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
                    proposal_id, gate["passed_count"], gate["total"]
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
                logger.info(
                    f"Approved compliance fix #{item['id']} for {rule_id}: "
                    f"success={result.get('success')}"
                )
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
            post_type = data.get("post_type", "personal")  # personal or company
            company_slug = data.get("company_slug", "kytran-empowerment-inc")
            agent_id = data.get("browser_agent_id", 342)
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
                    text = _re.sub(r'^[🇨🇦⚜️🇫🇷\s]*(?:English|Français québécois|Anglais|Translation in Québécois French)\s*:?\s*\n', '', text, flags=_re.MULTILINE)
                    # Strip Markdown headers (### Title)
                    text = _re.sub(r'^#{1,6}\s+', '', text, flags=_re.MULTILINE)
                    # Strip **bold** markers
                    text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=_re.DOTALL)
                    return text.strip()

                content = _clean_linkedin(content)

                if post_type == "creed":
                    skill = "linkedin_creed_post"
                elif post_type == "company":
                    skill = "linkedin_company_post"
                else:
                    skill = "linkedin_post"
                params = {"content": content, "hashtags": hashtags}
                if post_type == "creed":
                    # Creed slug: action_data > env var > numeric default
                    creed_slug = data.get("company_slug") or _os.getenv(
                        "LINKEDIN_CREED_SLUG", "115977300"
                    )
                    params["company_slug"] = creed_slug
                    company_slug = creed_slug
                elif post_type == "company":
                    params["company_slug"] = company_slug

                result = run_skill_sync(skill, params, agent_id=agent_id, timeout_s=120)

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
                                   (content, hashtags, post_type, company_slug, status, approval_id, posted_at)
                               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
                            (
                                content,
                                hashtags,
                                post_type,
                                company_slug if post_type in ("company", "creed") else None,
                                "posted" if result.get("success") else "failed",
                                item["id"],
                            ),
                        )
                        _lc.commit()
                    finally:
                        _lcur.close()
                        _lc.close()
                except Exception as log_err:
                    logger.warning(f"linkedin_post_log write failed: {log_err}")

                logger.info(
                    "LinkedIn post approved and executed: success=%s", result.get("success")
                )

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

                return {"executed": True, "result": result}
            except Exception as li_err:
                logger.error(f"LinkedIn post execution failed: {li_err}")
                return {"executed": False, "error": str(li_err)}

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

        else:
            logger.warning(f"Unknown approved action type: {action_type}")
            return {"skipped": True, "reason": f"Unknown action type: {action_type}"}

    # ------------------------------------------------------------------
    # Dependabot Vulnerability Scan
    # ------------------------------------------------------------------

    def _run_dependabot_scan(self):
        """Agent Loop Job: Poll Dependabot alerts and triage pending repairs."""
        try:
            from tools.dev_pipeline.services.dependabot_service import (
                poll_and_ingest,
                sync_manifest_registry,
            )
            from tools.dev_pipeline.services.forge_triage import triage_pending_queue

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
                "http://host.docker.internal:8101/api/trading/run-cycle",
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
                    hashlib.md5(
                        datetime.now().strftime("%Y-%m-%d").encode()
                    ).hexdigest()[:8],
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
                            len(
                                [
                                    i
                                    for i in issues
                                    if i.get("type") == "security"
                                ]
                            ),
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
                    scanned += 1

                except Exception as scan_err:
                    logger.warning(
                        f"Proactive scan failed for {file_path}: {scan_err}"
                    )

            duration_ms = int((time.time() - start) * 1000)
            if scanned > 0:
                logger.info(
                    f"Proactive scan: {scanned}/{len(scan_files)} files scanned "
                    f"({duration_ms}ms)"
                )
                # Auto-heal: queue any new low/medium proposals through tiered approval
                # so fixes flow straight into F.O.R.G.E. review → sandbox → deploy.
                try:
                    import sys as _sys
                    _sys.path.insert(0, "/mnt/archie_brain/platform_v2")
                    from services.proposal_service import request_tiered_deploy_approval
                    from database import get_db_cursor as _gdc

                    with _gdc() as (_ac, _acur):
                        _acur.execute(
                            """SELECT id FROM improvement_proposals
                               WHERE status = 'pending'
                               AND risk_level IN ('low', 'medium')
                               AND proposed_at > NOW() - INTERVAL '10 minutes'
                               ORDER BY proposed_at DESC LIMIT 20"""
                        )
                        new_ids = [r["id"] for r in _acur.fetchall()]

                    auto_queued = 0
                    for pid in new_ids:
                        try:
                            with _gdc(commit=True) as (_bc, _bcur):
                                _bcur.execute(
                                    "UPDATE improvement_proposals "
                                    "SET status='ready_for_review' "
                                    "WHERE id=%s AND status='pending'",
                                    (pid,),
                                )
                            r = request_tiered_deploy_approval(pid)
                            if r.get("success") or r.get("pending"):
                                auto_queued += 1
                        except Exception as _ae:
                            logger.debug("auto-heal queue #%s: %s", pid, _ae)

                    if auto_queued:
                        logger.info(
                            "Proactive scan auto-heal: queued %d/%d proposals",
                            auto_queued, len(new_ids),
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

            scan_id = store_dependency_findings(findings)

            # Alert on critical/high
            critical = [
                f for f in findings if f["severity"] in ("critical", "high")
            ]
            if critical:
                self._send_telegram(
                    "\u26a0\ufe0f *Dependency Audit*\n\n"
                    f"*{len(critical)}* critical/high CVEs found:\n"
                    + "\n".join(
                        f"- {f['package']}=={f['version']}: {f['vuln_id']}"
                        for f in critical[:5]
                    )
                    + f"\n\n[View in Repair Bay]"
                    f"(http://192.168.1.200:3000/tools/repair-bay)"
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
                    "finding_sizes": {
                        k: len(v) for k, v in result["findings"].items()
                    },
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
                    logger.warning(
                        "Misroute audit: Telegram dispatch failed: %s", tg_err
                    )

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
        "run_qa_suite": 300,
        "run_misroute_audit": 120,
        "run_misroute_to_proposal_adapter": 120,
        "check_dep_drift": 60,
        "health_check": 30,
        "check_platform_health": 30,
    }
    _DELEGATE_DEFAULT_TIMEOUT_SECS = 360  # dispatcher 300s + 60s buffer

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
        start = time.time()
        processed = 0
        failed = 0
        try:
            import sys
            from concurrent.futures import (
                ThreadPoolExecutor,
                TimeoutError as FutureTimeoutError,
            )

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.delegation_service import (
                emit_delegation_event,
                execute_delegated_task,
                fetch_pending_delegations,
                mark_task_completed,
                mark_task_failed,
                mark_task_in_progress,
            )

            tasks = fetch_pending_delegations(limit=3)
            if not tasks:
                # Silent no-op when queue is empty — avoids autonomy_loop_log spam.
                return

            # Lazy-init a dedicated single-thread executor. Reused across cycles.
            # Single worker → one delegated task in flight at a time, matching the
            # design's serial-claim model; the loop iterates 3 tasks max per cycle.
            if not hasattr(self, "_delegate_pool"):
                self._delegate_pool = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="delegate-task",
                )

            for task in tasks:
                task_id = task["id"]
                mark_task_in_progress(task_id)

                # Capability + source for Unified Comms event payload.
                args = task.get("delegation_args") or {}
                if isinstance(args, str):
                    try:
                        import json as _json

                        args = _json.loads(args)
                    except Exception:
                        args = {}
                capability = args.get("capability", "unknown")
                delegation_source = task.get("delegation_source") or "mcp_client"
                streaming_channel = task.get("streaming_channel")

                emit_delegation_event(
                    task_id,
                    "start",
                    capability=capability,
                    delegation_source=delegation_source,
                    streaming_channel=streaming_channel,
                )

                timeout_secs = self._DELEGATE_CAPABILITY_TIMEOUTS.get(
                    capability, self._DELEGATE_DEFAULT_TIMEOUT_SECS
                )

                try:
                    future = self._delegate_pool.submit(execute_delegated_task, task)
                    try:
                        result = future.result(timeout=timeout_secs)
                    except FutureTimeoutError:
                        # Outer shield fired. mark_task_failed sets status='blocked'
                        # so the row is retry-able once the underlying issue clears.
                        # The orphaned thread keeps running until it finishes/dies;
                        # this is strictly better than freezing APScheduler.
                        timeout_summary = (
                            f"Delegate worker timed out after {timeout_secs}s "
                            f"(capability={capability})"
                        )
                        logger.error(
                            "Delegate task #%s %s — marking blocked, worker continues",
                            task_id,
                            timeout_summary,
                        )
                        try:
                            mark_task_failed(task_id, timeout_summary)
                            emit_delegation_event(
                                task_id,
                                "fail",
                                capability=capability,
                                summary=timeout_summary,
                                delegation_source=delegation_source,
                                streaming_channel=streaming_channel,
                            )
                        except Exception:
                            pass
                        failed += 1
                        continue

                    if result.get("success"):
                        summary = result.get("summary", "")
                        mark_task_completed(task_id, summary)
                        emit_delegation_event(
                            task_id,
                            "complete",
                            capability=capability,
                            summary=summary,
                            delegation_source=delegation_source,
                            streaming_channel=streaming_channel,
                        )
                        processed += 1
                    else:
                        fail_summary = (
                            result.get("summary")
                            or result.get("error")
                            or "Unknown failure"
                        )
                        mark_task_failed(task_id, fail_summary)
                        emit_delegation_event(
                            task_id,
                            "fail",
                            capability=capability,
                            summary=fail_summary,
                            delegation_source=delegation_source,
                            streaming_channel=streaming_channel,
                        )
                        failed += 1
                except Exception as task_err:
                    logger.exception(
                        "Delegate task #%s raised during execute", task_id
                    )
                    try:
                        mark_task_failed(task_id, f"Executor exception: {task_err}")
                        emit_delegation_event(
                            task_id,
                            "fail",
                            capability=capability,
                            summary=f"Executor exception: {task_err}",
                            delegation_source=delegation_source,
                            streaming_channel=streaming_channel,
                        )
                    except Exception:
                        pass
                    failed += 1

            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle(
                job_name="delegate_task_worker",
                items_processed=processed,
                items_failed=failed,
                duration_ms=duration_ms,
                details={
                    "claimed": len(tasks),
                    "completed": processed,
                    "failed": failed,
                },
            )
            if processed or failed:
                logger.info(
                    "delegate_task_worker: claimed=%d done=%d failed=%d in %dms",
                    len(tasks),
                    processed,
                    failed,
                    duration_ms,
                )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error("delegate_task_worker failed: %s", e)
            try:
                self._log_cycle(
                    job_name="delegate_task_worker",
                    items_processed=processed,
                    items_failed=max(failed, 1),
                    duration_ms=duration_ms,
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
                        telegram_send(
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
                    except Exception as tg_err:
                        logger.warning("triage_consumer: Telegram send failed: %s", tg_err)

            logger.info(
                "triage_consumer: processed=%d escalated=%d",
                len(reports),
                escalated,
            )
        except Exception as e:
            logger.error("triage_consumer failed: %s", e)

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
                    # Phase 3: Autonomous actions
                    actions_taken = self._kin_execute_actions(
                        assessment.get("actions", []), conn
                    )
                    # Phase 4a: C.R.E.E.D. ethics filing
                    flags_filed = self._kin_file_creed(
                        assessment.get("creed_flags", []), conn
                    )
                finally:
                    conn.close()

                # Phase 4b: A.R.C.H.I.E. severity report
                try:
                    self._kin_report_to_archie(
                        assessment["archie_report"], actions_taken, flags_filed
                    )
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
                    logger.warning(
                        "K.I.N. digest: system_notifications insert failed: %s", notify_err
                    )

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
        _platform_v2 = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "platform_v2"
        )
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

    def _kin_execute_actions(self, actions: list, conn) -> int:
        """Phase 3: Execute K.I.N.'s autonomous welfare decisions. Returns count of applied actions."""
        import sys as _sys
        import os as _os
        import psycopg2.extras as _extras
        from datetime import date as _date
        _platform_v2 = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "platform_v2"
        )
        _sys.path.insert(0, _platform_v2)
        from services.agent_service import recover_idle, transition_shift_state
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
                                "kin_welfare_action", "welfare_ethics", agent_id,
                                action_type or "unknown", reason, "skipped",
                                _extras.Json({"filed_by": "K.I.N.", "digest_date": str(_date.today()), "skip_reason": "missing agent_id or action_type"}),
                            ),
                        )
                        conn.commit()
                    finally:
                        cur.close()
                except Exception:
                    pass
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
                            "kin_welfare_action", "welfare_ethics", agent_id,
                            action_type, reason, outcome,
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
                            _extras.Json({
                                "severity": flag.get("severity", "low"),
                                "filed_by": "K.I.N.",
                                "digest_date": str(_date.today()),
                            }),
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
        _platform_v2 = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "platform_v2"
        )
        _sys.path.insert(0, _platform_v2)
        from services.telegram_service import send as tg_send

        severity = archie_report.get("severity", "info")
        message = archie_report.get("message", "K.I.N. welfare assessment complete.")
        if actions_taken or flags_filed:
            message += f"\n\n✅ Actions taken: {actions_taken} | C.R.E.E.D. filings: {flags_filed}"

        common_kwargs = dict(
            source_agent="K.I.N.",
            source_department="Human Resources & Culture",
            source_module="agent_loop",
        )

        if severity in ("critical", "alert"):
            tg_send(
                category="alert",
                title="K.I.N. Welfare Alert",
                message=message,
                **common_kwargs,
            )
        elif severity == "warning":
            tg_send(
                category="info",
                title="K.I.N. Welfare Digest",
                message=message,
                **common_kwargs,
            )
        # severity == "info" → no Telegram; A.R.C.H.I.E. stays quiet on healthy days

        logger.info(
            "K.I.N. welfare report sent: severity=%s actions=%d creed=%d",
            severity, actions_taken, flags_filed,
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

    def _run_email_imap_sync(self):
        """Poll IMAP for provisioned mailboxes and sync to email_activity_log."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM email_mailboxes WHERE provisioned=TRUE AND active=TRUE"
                )
                count = cur.fetchone()["cnt"]
            logger.info(
                "email_imap_sync: %d provisioned mailboxes (full IMAP sync requires Phase 2 credential storage)",
                count,
            )
        except Exception as e:
            logger.error("email_imap_sync failed: %s", e)

    def _run_repo_health_check(self):
        """Daily per-repo GitHub presence health check (Project #247, Task #1803)."""
        try:
            from tools.repair_bay.services.repo_health_service import run_health_checks

            result = run_health_checks()
            logger.info(
                "repo_health_check: checked=%d healthy=%d unhealthy=%d",
                result.get("checked"),
                result.get("healthy"),
                result.get("unhealthy"),
            )
        except Exception as e:
            logger.error("repo_health_check failed: %s", e)

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
                    logger.warning(
                        "F.O.R.G.E. dep drift: Telegram dispatch failed: %s", tg_err
                    )

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
            from services.knowledge_service import store_knowledge
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
            store_knowledge(
                title=f"Fleet Capacity Report {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                content="\n".join(content_lines),
                knowledge_type="vault_note",
                category="fleet_capacity",
                tags=["fleet", "capacity-report", "autonomy"],
                importance_score=0.5,
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
            logger.info(
                "github_presence_audit: repos=%d success=%s",
                result.get("repo_count"),
                result.get("success"),
            )
        except Exception as e:
            logger.error("github_presence_audit failed: %s", e)

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
                    logger.warning(
                        "V.I.G.I.L. heartbeat: Telegram dispatch failed: %s", tg_err
                    )
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
                msg = (
                    f"\U0001f310 *Public IP Changed*\n\n"
                    f"`{old}` \u2192 `{new}`\n"
                )
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
                logger.debug(
                    "DDNS: IP unchanged (%s)", result.get("current_ip")
                )

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
            nt_pass = os.getenv(
                "NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin")
            )

            VPN_L7 = {
                "OpenVPN", "WireGuard", "IPSec", "PPTP", "L2TP",
                "Tor", "SOCKS", "SoftEther", "Tailscale",
            }
            VPN_L7_PARTIAL = [
                "Tailscale", "NordVPN", "ExpressVPN",
                "Surfshark", "ProtonVPN", "Mullvad",
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
                    total_gb = round(dev["total"] / (1024 ** 3), 1)
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
                                headers=headers, timeout=10,
                            )
                            if resp.status_code != 200:
                                continue
                            content = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
                            scan = scanner.scan_dependency_file(content, dep_file, owner_repo)
                            total_entries += _store_dependency_scan(cur, scan)
                            total_scans += 1
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
            self._log_cycle("weekly_dependency_scan", total_scans, 0, duration_ms,
                           details={"files_scanned": total_scans, "entries_stored": total_entries})
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("weekly_dependency_scan", 0, 1, duration_ms, error_message=str(e))

    def _health_probe(self):
        """Service health probe every 15 min — migrated from app.py."""
        start = time.time()
        try:
            from tools.dev_hq.routes import _run_and_store_health_check
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

    def _media_hub_health_check(self):
        """Probe every enabled media_hub_services row and persist health state.

        Delegates to tools.media_hub.health.run_health_checks so the logic
        lifts cleanly during Project #273 standalone extraction.
        """
        start = time.time()
        try:
            from tools.media_hub.health import run_health_checks

            summary = run_health_checks()
            self._log_cycle(
                "media_hub_health_check",
                summary["healthy"],
                summary["unhealthy"] + summary["errors"],
                int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.error(f"Error in media_hub_health_check: {e}")
            self._log_cycle(
                "media_hub_health_check", 0, 1, int((time.time() - start) * 1000), error_message=str(e)
            )

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

            missing = {m for m in desired if m not in loaded and f"{m}:latest" not in loaded}
            if not missing:
                self._log_cycle("ollama_model_health", len(loaded), 0, int((time.time() - start) * 1000))
                return

            ram_free = psutil.virtual_memory().available / (1024**3)
            reloaded = 0
            for model_name in missing:
                ram_free = psutil.virtual_memory().available / (1024**3)
                if ram_free < 10:
                    break
                endpoint = desired[model_name]
                use_gpu = model_name in gpu_models or f"{model_name}:latest" in gpu_models
                try:
                    # keep_alive="15m" — was -1 which means "pin in RAM forever".
                    # -1 defeated Department HQ's ability to auto-unload idle
                    # agents and caused ~64GB of models to accumulate until
                    # swap maxed out. 15m lets Dept HQ's lifecycle manager
                    # reclaim idle model RAM.
                    if endpoint == "embed":
                        data = {"model": model_name, "input": "health", "keep_alive": "15m"}
                    else:
                        opts = {"num_predict": 1}
                        if not use_gpu:
                            opts["num_gpu"] = 0
                        data = {"model": model_name, "prompt": "health", "stream": False, "options": opts, "keep_alive": "15m"}
                    timeout = 600 if "coder" in model_name else 300
                    r = req.post(f"{ollama_host}/api/{endpoint}", json=data, timeout=timeout)
                    if r.status_code == 200:
                        reloaded += 1
                except Exception as e:
                    logger.warning(f"Ollama health: {model_name} failed: {e}")

            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("ollama_model_health", reloaded, len(missing) - reloaded, duration_ms,
                           details={"missing": len(missing), "reloaded": reloaded})
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
                    "ollama_placement_telemetry", 0, 0,
                    int((time.time() - start) * 1000),
                )
                return

            gpu = sum(1 for e in events if e.get("placement") == "gpu")
            cpu = sum(1 for e in events if e.get("placement") == "cpu")
            total = gpu + cpu
            cpu_share = cpu / max(total, 1)

            prev = getattr(self, "_last_placement_summary", None)
            anomaly = (
                cpu_share > 0.5
                and prev is not None
                and prev.get("cpu_share", 0) > 0.5
            )
            self._last_placement_summary = {
                "ts": time.time(),
                "gpu": gpu,
                "cpu": cpu,
                "cpu_share": cpu_share,
            }

            self._log_cycle(
                "ollama_placement_telemetry",
                processed=total,
                failed=cpu if anomaly else 0,
                duration_ms=int((time.time() - start) * 1000),
                error_message=(
                    f"sustained_cpu_fallback cpu_share={cpu_share:.2f}"
                    if anomaly
                    else None
                ),
            )
        except Exception as e:
            logger.error(f"ollama_placement_telemetry failed: {e}")
            self._log_cycle(
                "ollama_placement_telemetry", 0, 1,
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
            import json
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
                jobs_summary.append({
                    "id": j.id,
                    "name": j.name or j.id,
                    "next_run": nr.isoformat() if nr else None,
                    "trigger": str(j.trigger) if j.trigger else "",
                })

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
                cur.execute(
                    "DELETE FROM scheduler_heartbeat WHERE ts < now() - interval '24 hours'"
                )
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
                from datetime import datetime as _dt, timedelta as _td

                with get_db_cursor() as (_c, _cur):
                    _cur.execute(
                        "SELECT MAX(created_at) AS latest FROM backup_log WHERE status='success' AND tier='primary'"
                    )
                    _row = _cur.fetchone()
                latest = _row["latest"] if _row else None
                if latest is None:
                    if now - self._watchdog_last_alert.get("backup_missing", 0) > dedup_s:
                        triggered.append(("backup_missing", "No successful primary backups recorded (empty backup_log)"))
                        self._watchdog_last_alert["backup_missing"] = now
                else:
                    latest_naive = latest.replace(tzinfo=None) if hasattr(latest, "tzinfo") and latest.tzinfo else latest
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
                            f"{_t}={'never' if _d is None else f'{_d:.1f}d'}"
                            for _t, _d in _stale_tiers
                        )
                        triggered.append((_key, f"Backup tiers stale (>14d): {_details}"))
                        self._watchdog_last_alert[_key] = now
            except Exception as _te:
                logger.warning(f"watchdog tier-health check failed: {_te}")

            for category, msg in triggered:
                try:
                    from services.telegram_service import send_system

                    send_system(
                        title=f"Platform Watchdog: {category.upper()} pressure",
                        message=f"{msg}\nload1={load1:.1f} mem_avail={mem_avail_gb:.1f}GB swap_free={swap_free_gb:.2f}GB",
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
        """Reap orphaned bridge jobs that stopped updating (every 2 min)."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            reaped = dispatcher.reap_stale_jobs(max_age_minutes=5)
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
                cur.execute("""
                    UPDATE bridge_jobs
                    SET status = 'failed',
                        error_message = 'Auto-killed: job exceeded 30 minute timeout',
                        completed_at = NOW()
                    WHERE status = 'running'
                      AND created_at < NOW() - INTERVAL '30 minutes'
                    RETURNING id, job_type, agent_name, module_source
                """)
                killed = cur.fetchall()

            for job in killed:
                logger.warning(
                    f"Stuck job killed: #{job['id']} {job['job_type']} by {job['agent_name']}"
                )
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
                    suite_meta.get("base_url")
                    or os.environ.get("PLATFORM_URL", "http://localhost:3000")
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
                                base_url, auth["username"],
                            )
                        except Exception as auth_err:
                            logger.warning(
                                "QA scheduled: shared session pre-auth failed for %s as %s — "
                                "falling back to per-suite auth: %s",
                                base_url, auth["username"], auth_err,
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
                per_suite.append({
                    "suite_id": suite["id"],
                    "name": suite.get("name", "?"),
                    "passed": p,
                    "failed": f,
                    "errors": e,
                    "shared_session": use_shared,
                })
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
            from tools.department_hq.services.department_dispatcher import dispatch

            start = time.time()
            result = dispatch(
                capability="user_audit",
                prompt=(
                    "Run a daily user account audit for the A.R.C.H.I.E. platform. "
                    "Check for: (1) users inactive for more than 30 days, "
                    "(2) currently locked accounts (auth_events), "
                    "(3) expired or pending invites older than 7 days. "
                    "Summarise findings concisely. Flag anything that needs attention."
                ),
            )
            duration_ms = int((time.time() - start) * 1000)
            success = result.success if result else False
            self._log_cycle(
                "warden_user_audit",
                1 if success else 0,
                0 if success else 1,
                duration_ms,
                details={"response": result.response[:500] if result and result.response else "no response"},
            )
        except Exception as e:
            logger.error("warden_user_audit failed: %s", e)

    def _run_warden_backup_verify(self):
        """Daily backup integrity check — checksums, age, retention policy."""
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.department_hq.services.department_dispatcher import dispatch
            from database import get_db_cursor

            start = time.time()
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT type, status, created_at, size_bytes
                       FROM backups ORDER BY created_at DESC LIMIT 10"""
                )
                recent = cur.fetchall()

            summary = ", ".join(
                f"{r['type']}({r['status']}, {r['created_at'].strftime('%Y-%m-%d')})"
                for r in (recent or [])
            ) or "no backups found"

            result = dispatch(
                capability="backup_verify",
                prompt=(
                    f"Verify backup health. Recent backups: {summary}. "
                    "Check: (1) is the most recent DB backup less than 24h old? "
                    "(2) are any backups in failed/error status? "
                    "(3) is retention policy being followed (7 daily, 4 weekly)? "
                    "Flag anything that needs attention."
                ),
            )
            duration_ms = int((time.time() - start) * 1000)
            success = result.success if result else False
            self._log_cycle(
                "warden_backup_verify",
                1 if success else 0,
                0 if success else 1,
                duration_ms,
                details={"response": result.response[:500] if result and result.response else "no response"},
            )
        except Exception as e:
            logger.error("warden_backup_verify failed: %s", e)

    def _run_warden_compliance_check(self):
        """Weekly compliance scan across all 4 admin modules."""
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from tools.department_hq.services.department_dispatcher import dispatch

            start = time.time()
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
            duration_ms = int((time.time() - start) * 1000)
            success = result.success if result else False
            self._log_cycle(
                "warden_compliance_check",
                1 if success else 0,
                0 if success else 1,
                duration_ms,
                details={"response": result.response[:500] if result and result.response else "no response"},
            )
        except Exception as e:
            logger.error("warden_compliance_check failed: %s", e)


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
            cur.execute("""
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
            """, (lookback_days, min_tasks))
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
                cur.execute("""
                    SELECT id, confidence, last_degraded_at
                    FROM agent_learning_log
                    WHERE agent_id = %s AND skill_name = %s
                    ORDER BY confidence DESC LIMIT 1
                """, (agent_id, capability))
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
                    if hasattr(last_degraded, 'tzinfo') and last_degraded.tzinfo is None:
                        last_degraded = last_degraded.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
                    if (now_utc - last_degraded).total_seconds() < 86400:
                        continue

                # Guard: skip if already in training for this skill
                cur.execute("""
                    SELECT id FROM training_assignments
                    WHERE agent_id = %s AND skill_name = %s AND status IN ('pending', 'in_progress')
                    LIMIT 1
                """, (agent_id, capability))
                if cur.fetchone():
                    continue

                # Degrade: reduce confidence by 0.2
                new_confidence = max(0.1, confidence - 0.2)
                cur.execute("""
                    UPDATE agent_learning_log
                    SET confidence = %s, last_degraded_at = NOW(),
                        degradation_count = COALESCE(degradation_count, 0) + 1
                    WHERE id = %s
                """, (round(new_confidence, 2), skill_row["id"]))

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
                    cur.execute("""
                        SELECT capability, error_message, module_source
                        FROM task_execution_log
                        WHERE agent_id = %s AND capability = %s AND success = FALSE
                          AND created_at > NOW() - INTERVAL '1 day' * %s
                        ORDER BY created_at DESC LIMIT 10
                    """, (agent_id, capability, lookback_days))
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
                                f"What specific patterns are causing failures? "
                                f"Give 2-3 actionable corrections the agent should apply."
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
                cur.execute("""
                    INSERT INTO training_assignments
                    (agent_id, skill_name, target_proficiency, current_proficiency,
                     status, started_at, target_completion,
                     failure_analysis, degradation_triggered, failure_summary)
                    VALUES (%s, %s, %s, %s, 'in_progress', NOW(), NOW() + INTERVAL '1 hour' * %s,
                            %s, TRUE, %s)
                """, (
                    agent_id, capability, target_level, new_level,
                    training_hours,
                    failure_analysis,
                    json.dumps(failure_summary),
                ))

                # Create HR alert
                self._create_hr_alert(
                    cur, agent_id,
                    "proficiency_degradation", "warning",
                    f"{display_name}: degraded to Lv{new_level} on {capability}",
                    f"Agent {display_name} dropped from Lv{current_level} to Lv{new_level} "
                    f"on {capability} ({failure_rate}% failure rate over {row['total']} tasks). "
                    f"Auto-training started ({training_hours}h).",
                    {"capability": capability, "failure_rate": failure_rate,
                     "old_level": current_level, "new_level": new_level,
                     "training_hours": training_hours},
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
            cur.execute("""
                SELECT id FROM agent_alerts
                WHERE agent_id = %s AND alert_type = %s AND resolved = FALSE
                  AND created_at > NOW() - INTERVAL '1 hour'
                LIMIT 1
            """, (agent_id, alert_type))
            if cur.fetchone():
                return 0  # Already alerted recently

            cur.execute("""
                INSERT INTO agent_alerts
                (agent_id, alert_type, severity, title, message, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (agent_id, alert_type, severity, title, message,
                  json.dumps(details or {})))

            # Log governance event for critical alerts
            if severity == "critical":
                log_governance_event(
                    "agent_welfare", f"alert_{alert_type}",
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
            from ai_bridge.telegram_gateway import TelegramGateway
            import asyncio

            # Find the running gateway instance
            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if not gateway or not gateway.is_running:
                return

            # Get unnotified alerts
            cur.execute("""
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
            """)
            alerts = cur.fetchall()
            if not alerts:
                return

            # Get authorized Telegram user
            cur.execute("""
                SELECT telegram_id FROM telegram_users
                WHERE is_authorized = TRUE AND user_id IS NOT NULL
                LIMIT 1
            """)
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
        status = (
            "error"
            if items_failed > 0 and items_processed == 0
            else "partial" if items_failed > 0 else "success"
        )
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
                failed_match = re.search(
                    r"Failed password for (?:invalid user )?(\S+) from (\S+)", line
                )
                if failed_match:
                    user = failed_match.group(1)
                    ip = failed_match.group(2)
                    failed_by_ip[ip] = failed_by_ip.get(ip, 0) + 1
                    if user == "root":
                        root_attempts.append(ip)
                    continue

                # Successful logins (Accepted)
                accepted_match = re.search(
                    r"Accepted \S+ for (\S+) from (\S+)", line
                )
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
                cur.execute("""
                    SELECT id, title, description, category, priority,
                           code_changes, file_path, plan_steps,
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
                """)
                proposals = cur.fetchall()

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
                            cur2.execute("""
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
                            """, (proposal[0],))
                    except Exception as db_err:
                        logger.error(f"[Fix Processor] DB update failed for proposal #{proposal[0]}: {db_err}")

            logger.info(
                f"[Fix Processor] Processed {succeeded + failed} proposals, "
                f"{succeeded} succeeded, {failed} failed"
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
            cur.execute("""
                SELECT a.id, a.name FROM agents a
                WHERE a.department = 'Engineering & Technology'
                  AND a.shift_state = 'active'
                ORDER BY a.name
                LIMIT 1
            """)
            agent = cur.fetchone()

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
                    cur.execute("""
                        UPDATE improvement_proposals
                        SET status = 'agent_assigned',
                            assigned_agent_id = %s
                        WHERE id = %s
                    """, (assigned_id, proposal_id))
                else:
                    cur.execute("""
                        UPDATE improvement_proposals
                        SET status = 'agent_assigned'
                        WHERE id = %s
                    """, (proposal_id,))
                logger.info(
                    f"[Fix Processor] Fleet agent {fleet_agent_info['agent_name']} "
                    f"on node {fleet_agent_info.get('node_name', '?')} assigned to proposal #{proposal_id}"
                )
            else:
                cur.execute("""
                    UPDATE improvement_proposals
                    SET status = 'agent_assigned',
                        assigned_agent_id = %s
                    WHERE id = %s
                """, (agent[0], proposal_id))

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
                        cur.execute("""
                            UPDATE improvement_proposals
                            SET status = 'approved', assigned_agent_id = NULL,
                                retry_count = retry_count + 1,
                                last_retry_at = NOW()
                            WHERE id = %s
                        """, (proposal_id,))
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
                logger.error(
                    f"[Fix Processor] Fleet dispatch failed for proposal #{proposal_id}"
                )
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute("""
                        UPDATE improvement_proposals
                        SET status = 'approved', assigned_agent_id = NULL,
                            retry_count = retry_count + 1,
                            last_retry_at = NOW()
                        WHERE id = %s
                    """, (proposal_id,))
                return
            response_text = fleet_result["response"]
            # Update assigned agent to fleet agent if we fell back mid-dispatch
            fleet_hub_id = fleet_agent_info.get("hub_agent_id")
            if fleet_hub_id:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute("""
                        UPDATE improvement_proposals
                        SET assigned_agent_id = %s
                        WHERE id = %s
                    """, (fleet_hub_id, proposal_id))

        # 6. Parse agent response
        try:
            fix_data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"[Fix Processor] Invalid JSON from agent for proposal #{proposal_id}")
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("""
                    UPDATE improvement_proposals
                    SET status = 'approved', assigned_agent_id = NULL,
                        retry_count = retry_count + 1
                    WHERE id = %s
                """, (proposal_id,))
            return

        # 7. Store agent's fix in proposal
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                UPDATE improvement_proposals
                SET contractor_proposal = %s,
                    status = 'in_progress'
                WHERE id = %s
            """, (Json(fix_data), proposal_id))

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
            fleet_agent_info["agent_name"] if fleet_agent_info and dispatch_source == "fleet"
            else (agent[1] if agent else "unknown")
        )
        dispatch_node = (
            fleet_agent_info.get("node_name", "remote") if fleet_agent_info and dispatch_source == "fleet"
            else "hub"
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
                cur.execute("""
                    SELECT content FROM knowledge_base
                    WHERE category = 'code_health'
                      AND knowledge_type = 'fix_pattern'
                      AND (tags::text ILIKE %s OR content ILIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (f"%{category}%", f"%{category}%"))
                row = cur.fetchone()
                if row:
                    return row[0]
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
                agent = svs.pick_agent_for_content()
                variables = {
                    "agent_name": agent.get("display_name") or agent.get("name", ""),
                    "department": agent.get("department", ""),
                    "personality_trait": (agent.get("personality", "") or "")[:100],
                    "personality_note": "",
                    "project_note": "",
                }
            else:
                quotes = [
                    ("The only way to do great work is to love what you do.", "Steve Jobs"),
                    ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
                    ("Success is not final, failure is not fatal: it is the courage to continue that counts.", "Winston Churchill"),
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
            if content_type == "agent_moment" and svs.should_auto_approve(rendered):
                approval_tier = "auto"

            # Create queue item
            item = svs.create_queue_item(
                template_id=template["id"],
                content_type=content_type,
                variables=variables,
                rendered=rendered,
                approval_tier=approval_tier,
                created_by="agent_loop",
            )
            logger.info("[SocialVideo] Created queue item id=%s type=%s tier=%s", item.get("id"), content_type, approval_tier)

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
                            if platform in ("instagram", "facebook"):
                                from tools.social_media.publishing_service import publish_video
                                result = publish_video(platform, video_path, caption, hashtags)
                                if result:
                                    post_urls[platform] = result
                            elif platform == "indeed":
                                from tools.social_media.platform_clients import get_indeed_client
                                result = get_indeed_client().post_video(video_path, caption, hashtags)
                                if result:
                                    post_urls[platform] = result
                        except Exception as platform_err:
                            logger.error("[SocialVideo] Publish failed for platform=%s item=%s: %s", platform, item["id"], platform_err)

                    new_status = "posted" if post_urls else "failed"
                    svs.update_queue_item(
                        item["id"],
                        status=new_status,
                        posted_at=now,
                        post_urls=_json.dumps(post_urls),
                    )
                    logger.info("[SocialVideo] Published item id=%s status=%s platforms=%s", item["id"], new_status, list(post_urls.keys()))

                except Exception as item_err:
                    logger.error("[SocialVideo] Publish error for item id=%s: %s", item.get("id"), item_err)

        except Exception as e:
            logger.error("[SocialVideo] Publish job failed: %s", e)


    def _social_video_slideshow_render(self):
        """Pick up draft social_video_queue items with images and render AutoShorts slideshows."""
        try:
            from platform_v2.tools.media_studio.services import social_video_service as svs
            from platform_v2.tools.media_studio.services.slideshow_generator import generate_slideshow
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
                            from platform_v2.tools.media_studio.services.slideshow_generator import _APP_ROOT
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
                    from platform_v2.tools.media_studio.services.slideshow_generator import _APP_ROOT as _SG_ROOT
                    def _to_web(p):
                        if p and p.startswith(_SG_ROOT):
                            return p[len(_SG_ROOT):]
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
            from platform_v2.tools.media_studio.services.calendar_service import (
                generate_themed_caption,
                get_empty_days_this_week,
                get_slots_due_for_generation,
            )
            from platform_v2.tools.media_studio.services.social_video_service import svq_create

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
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     "-u", f"{ag_user}:{ag_pass}",
                     "http://network_adguard:80/control/status"],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip() != "200":
                    issues.append("AdGuard is not responding")
            except Exception as e:
                issues.append(f"AdGuard check failed: {e}")

            # Check NPM (Nginx Proxy Manager) — critical for all HTTPS subdomains + OAuth
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Health.Status}}", "nginx_proxy_manager"],
                    capture_output=True, text=True, timeout=10
                )
                npm_status = result.stdout.strip()
                if npm_status != "healthy":
                    issues.append(f"NPM is {npm_status or 'not running'} — all HTTPS subdomains affected")
                    if npm_status in ("unhealthy", ""):
                        subprocess.run(["docker", "restart", "nginx_proxy_manager"], capture_output=True, timeout=30)
            except Exception as e:
                issues.append(f"NPM check failed: {e}")

            if issues:
                self._create_network_alert(
                    "service_down", "high", "health_monitor",
                    f"Service issues detected: {len(issues)}", {"issues": issues}
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
                        (r["host_name"], r["service_description"], r["status"], r["output"], r["performance_data"], r["last_check"]),
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
                            "new_device", "medium", "device_watcher",
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
                    "dns_anomaly", "medium", "dns_anomaly_detector",
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
                            "log_overflow", "high", "log_health_monitor",
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
                                    "ip_banned", "high", "threat_responder",
                                    f"IP {ip} banned by fail2ban jail {jail.get('jail', 'unknown')}",
                                    {"ip": ip, "jail": jail.get("jail", ""), "total_banned": jail.get("total_banned", 0)},
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
            cur.execute(
                "SELECT value FROM system_config WHERE key = 'creed_reporter_last_id'"
            )
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
                creed_category = CATEGORY_MAP.get(
                    event["event_category"], "accountability"
                )
                creed_severity = SEVERITY_MAP.get(
                    event.get("outcome", ""), "info"
                )
                payload = {
                    "event_type": event["event_type"] or "agent_action",
                    "source_platform": "archie",
                    "agent_id": str(event.get("agent_id") or "system"),
                    "agent_name": event.get("agent_name") or "System",
                    "category": creed_category,
                    "severity": creed_severity,
                    "description": (
                        f"{event['action']}: {event.get('reason') or event['event_type']}"
                    ),
                    "metadata": {
                        "original_category": event["event_category"],
                        "original_outcome": event.get("outcome"),
                        "archie_event_id": event["id"],
                    },
                }

                try:
                    resp = req.post(
                        f"{CREED_URL}/api/v1/events",
                        json=payload,
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
                    logger.warning(
                        "[CREED Reporter] Connection failed: %s", e
                    )
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

            conn.close()

            if reported > 0:
                logger.info(
                    "[CREED Reporter] Forwarded %d events (up to id %d)",
                    reported,
                    new_last_id,
                )

        except Exception as e:
            logger.error("[CREED Reporter] Job failed: %s", e)


# ---------------------------------------------------------------------------
# Job #47 — Chat Memory Extraction (module-level, no app context needed)
# ---------------------------------------------------------------------------


def _process_chat_memories():
    """Job #47: Extract conversation summaries and pinned memories from idle chats."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find conversations idle for 5+ minutes with unsummarized messages
        cur.execute("""
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
        """)
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
    cur.execute("""
        SELECT sender_type, message, timestamp
        FROM directory_messages
        WHERE conversation_id = %s
        ORDER BY timestamp ASC
    """, (convo['id'],))
    messages = cur.fetchall()

    if len(messages) < 2:
        return  # Not enough to summarize

    # Get agent info
    cur.execute("SELECT name, display_name, title FROM agents WHERE id = %s", (convo['agent_id'],))
    agent = cur.fetchone()
    if not agent:
        return
    agent_name = agent.get('display_name') or agent.get('name')

    # Build conversation text
    conv_text = ""
    for msg in messages:
        role = "User" if msg['sender_type'] == 'user' else agent_name
        conv_text += f"{role}: {msg['message']}\n"

    # Dispatch summarization via canonical module-level dispatch() — the
    # previous .dispatch() call on the instance silently AttributeError'd.
    from bridge_dispatcher import dispatch

    # Summary
    summary_result = dispatch(
        capability="summarize",
        prompt=f"Summarize this conversation in 2-3 sentences:\n\n{conv_text}",
        module_id="directory_memory",
        system_prompt="You are a helpful assistant. Provide a concise summary.",
        prefer_agent=agent.get('name'),
    )
    summary = (
        summary_result.response.strip()
        if summary_result and summary_result.success and summary_result.response
        else ''
    )

    if summary:
        cur.execute("""
            INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
            VALUES (%s, %s, 'summary', %s)
        """, (convo['agent_id'], convo['user_id'], summary))

    # Pinned memories
    pinned_result = dispatch(
        capability="summarize",
        prompt=f"What important facts should you remember about this user from this conversation? List each fact on its own line. Only include facts worth remembering for future conversations.\n\n{conv_text}",
        module_id="directory_memory",
        system_prompt="You are a helpful assistant. Extract key facts about the user.",
        prefer_agent=agent.get('name'),
    )
    pinned_text = (
        pinned_result.response.strip()
        if pinned_result and pinned_result.success and pinned_result.response
        else ''
    )

    if pinned_text:
        for line in pinned_text.split('\n'):
            line = line.strip().lstrip('•-* ')
            if line and len(line) > 10:
                cur.execute("""
                    INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
                    VALUES (%s, %s, 'pinned', %s)
                """, (convo['agent_id'], convo['user_id'], line))

    conn.commit()
