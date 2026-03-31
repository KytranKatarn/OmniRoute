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
from datetime import datetime
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
    """Push Telegram notification with Approve/Deny/Defer buttons for tier-2 items."""
    try:
        import requests as _req

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return

        # Build context-aware message
        lines = [f"\u26a0\ufe0f *Approval Request #{approval_id}*\n"]
        if action_type == "cloud_throughput_escalation":
            agent = action_data.get("original_agent", "?")
            model = action_data.get("escalated_model", "?")
            provider = action_data.get("escalated_provider", "?")
            cap = action_data.get("capability", "?")
            module = action_data.get("module_id", "?")
            lines.append(f"Type: Cloud Escalation")
            lines.append(f"Agent: {agent} (busy)")
            lines.append(f"Escalate to: {model} ({provider})")
            lines.append(f"Capability: {cap}")
            lines.append(f"Module: {module}")
        elif action_type == "create_agent":
            cap = action_data.get("capability", "?")
            department = action_data.get("department", action_data.get("station_code", "?"))
            lines.append(f"Type: Create New Agent")
            lines.append(f"Capability: {cap}")
            lines.append(f"Department: {department}")
        else:
            lines.append(f"Type: {action_type}")

        if reason:
            lines.append(f"\nReason: {reason}")

        text = "\n".join(lines)

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Approve", "callback_data": f"esc_approve_{approval_id}"},
                    {"text": "Deny", "callback_data": f"esc_deny_{approval_id}"},
                    {"text": "Defer 1hr", "callback_data": f"esc_defer_{approval_id}"},
                ]
            ]
        }

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_id FROM telegram_users "
            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        for row in rows:
            _req.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": row[0],
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": keyboard,
                },
                timeout=15,
            )
        logger.info(f"Telegram approval notification sent for #{approval_id}")
    except Exception as e:
        logger.warning(f"Telegram approval notification failed: {e}")


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
    action_type: str, cur
) -> bool:
    """Check if a pending approval of the same type already exists. Returns True if duplicate found."""
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

        # Dedup: skip if there's already a pending approval of the same type
        if effective_tier > 1 and _check_existing_approval(action_type, cur):
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
    "crew_wellness_tick": "Human Resources & Culture",
    "ollama_model_health": "Operations & Infrastructure",
    "media_queue_cleanup": "Creative & Design",
    "media_export_cleanup": "Creative & Design",
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

    def start(self):
        """Attach agent loop jobs to the scheduler."""
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

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

        self.scheduler.add_job(
            with_app_context(self._check_email_inbox),
            trigger=IntervalTrigger(minutes=5),
            id="agent_email_inbox",
            name="Agent Loop: Email Inbox Check",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._auto_analyze_emails),
            trigger=IntervalTrigger(minutes=10),
            id="agent_email_analyze",
            name="Agent Loop: Auto-Analyze Emails",
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

        self.scheduler.add_job(
            with_app_context(self._track_agent_hr),
            trigger=IntervalTrigger(minutes=5),
            id="agent_hr_tracker",
            name="Agent Loop: HR Tracker",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._run_ethics_monitoring),
            trigger=IntervalTrigger(minutes=15),
            id="agent_ethics_monitoring",
            name="Agent Loop: Ethics Monitoring",
            replace_existing=True,
        )

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
            with_app_context(self._process_training_tick),
            trigger=IntervalTrigger(minutes=5),
            id="agent_training_tick",
            name="Agent Loop: Training Progression Tick",
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
            with_app_context(self._recover_idle_welfare),
            trigger=IntervalTrigger(minutes=30),
            id="agent_welfare_recovery",
            name="Agent Loop: Welfare Recovery",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._archive_stale_notifications),
            trigger=IntervalTrigger(hours=6),
            id="agent_notification_cleanup",
            name="Agent Loop: Stale Notification Archiver",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._volunteer_idle_agents),
            trigger=IntervalTrigger(minutes=5),
            id="agent_idle_volunteering",
            name="Agent Loop: Idle Volunteering",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._discover_network_devices),
            trigger=IntervalTrigger(minutes=5),
            id="agent_network_discovery",
            name="Agent Loop: Network Device Discovery",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._update_performance_rankings),
            trigger=IntervalTrigger(minutes=15),
            id="agent_performance_rankings",
            name="Agent Loop: Performance Rankings",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_media_schedules),
            trigger=IntervalTrigger(minutes=15),
            id="agent_media_generation",
            name="Agent Loop: Media Generation Schedules",
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
        self.scheduler.add_job(
            with_app_context(self._deduplicate_knowledge),
            trigger=IntervalTrigger(hours=24),
            id="knowledge_deduplication",
            name="Agent Loop: Knowledge Deduplication",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._index_claude_sessions),
            trigger=IntervalTrigger(hours=12),
            id="session_indexer",
            name="Agent Loop: Claude Session Indexer",
            replace_existing=True,
        )
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

        self.scheduler.add_job(
            with_app_context(self._run_security_audit),
            trigger=CronTrigger(day_of_week="sun", hour=3),
            id="agent_security_audit",
            name="Agent Loop: Weekly Security Audit",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._check_ssl_expiry),
            trigger=IntervalTrigger(hours=24),
            id="agent_ssl_expiry_check",
            name="Agent Loop: SSL Certificate Expiry Check",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._daily_dns_report),
            trigger=CronTrigger(hour=7, minute=0),
            id="agent_daily_dns_report",
            name="Agent Loop: Daily DNS Report",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._detect_query_spike),
            trigger=IntervalTrigger(hours=1),
            id="agent_query_spike_detect",
            name="Agent Loop: DNS Query Spike Detection",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._check_camera_anomaly),
            trigger=IntervalTrigger(hours=1),
            id="agent_camera_anomaly",
            name="Agent Loop: Camera Motion Anomaly",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._run_auto_block),
            trigger=IntervalTrigger(minutes=15),
            id="agent_auto_block",
            name="Agent Loop: Auto-Block Pipeline",
            replace_existing=True,
        )
        self.scheduler.add_job(
            with_app_context(self._check_mission_schedule),
            trigger=IntervalTrigger(minutes=5),
            id="agent_mission_schedule",
            name="Agent Loop: Mission Profile Schedule",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._daily_code_metrics_scan),
            trigger=CronTrigger(hour=3, minute=0),
            id="agent_code_metrics",
            name="Agent Loop: Daily Code Metrics Scan",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._pattern_compliance_check),
            trigger=CronTrigger(hour=4, minute=0),
            id="agent_pattern_compliance",
            name="Agent Loop: Pattern Compliance Check",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_fleet_health),
            trigger=IntervalTrigger(seconds=30),
            id="agent_fleet_health",
            name="Agent Loop: Fleet Health Monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._check_mesh_health),
            trigger=IntervalTrigger(seconds=60),
            id="agent_mesh_health",
            name="Agent Loop: Mesh VPN Health Monitor",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._save_model_state),
            trigger=IntervalTrigger(minutes=5),
            id="agent_model_state_save",
            name="Agent Loop: Model State Persistence",
            replace_existing=True,
        )

        self.scheduler.add_job(
            with_app_context(self._hourly_uncommitted_check),
            trigger=IntervalTrigger(hours=1),
            id="agent_uncommitted_check",
            name="Agent Loop: Uncommitted Change Monitor",
            replace_existing=True,
        )

        # Job #47 — Chat memory extraction (every 2 minutes)
        self.scheduler.add_job(
            _process_chat_memories,
            trigger=IntervalTrigger(minutes=2),
            id="job_47_chat_memories",
            name="Chat memory extraction",
            replace_existing=True,
        )

        # Job #48 — Auto-execute approved dev pipeline proposals
        self.scheduler.add_job(
            with_app_context(self._auto_execute_proposals),
            trigger=IntervalTrigger(minutes=30),
            id="agent_auto_execute_proposals",
            name="Agent Loop: Auto-Execute Dev Proposals",
            replace_existing=True,
        )

        # Job #49 — Consciousness analysis batch (every 6h)
        self.scheduler.add_job(
            with_app_context(self._consciousness_analysis_batch),
            trigger=IntervalTrigger(hours=6),
            id="agent_consciousness_analysis",
            name="Agent Loop: Consciousness Analysis Batch",
            replace_existing=True,
        )

        # Job #50 — Consciousness embedding batch (every 4h)
        self.scheduler.add_job(
            with_app_context(self._consciousness_embedding_batch),
            trigger=IntervalTrigger(hours=4),
            id="agent_consciousness_embedding",
            name="Agent Loop: Consciousness Embedding Batch",
            replace_existing=True,
        )

        # Job #51 — Daily Code Health Digest via Telegram (8:00 AM)
        self.scheduler.add_job(
            with_app_context(self._daily_code_health_digest),
            trigger=CronTrigger(hour=8, minute=0),
            id="agent_code_health_digest",
            name="Agent Loop: Daily Code Health Digest",
            replace_existing=True,
        )

        # Job #55 — Daily Code Health Scan (2:00 AM, before 8 AM digest)
        self.scheduler.add_job(
            with_app_context(self._daily_code_health_scan),
            trigger=CronTrigger(hour=2, minute=0),
            id="agent_code_health_scan",
            name="Agent Loop: Daily Code Health Scan",
            replace_existing=True,
        )

        # Job #58 — Automated Module Audit (daily 3:30 AM, after Job #40 snapshot)
        self.scheduler.add_job(
            with_app_context(self._automated_module_audit),
            trigger=CronTrigger(hour=3, minute=30),
            id="agent_automated_module_audit",
            name="Agent Loop: Automated Module Audit",
            replace_existing=True,
        )

        # Job #52 — Competitor landscape auto-scan (every 2 weeks)
        self.scheduler.add_job(
            with_app_context(self._competitor_landscape_scan),
            trigger=IntervalTrigger(days=14),
            id="agent_competitor_scan",
            name="Agent Loop: Competitor Landscape Scan",
            replace_existing=True,
        )

        # Job #54 — Skill sync: extract learned skills from KB to Claude rules
        self.scheduler.add_job(
            with_app_context(self._sync_learned_skills),
            trigger=IntervalTrigger(hours=6),
            id="agent_skill_sync",
            name="Agent Loop: Skill Sync to Claude",
            replace_existing=True,
        )

        # Job #55 — GitHub auto-pull: refresh tracked repos and re-index changed files
        self.scheduler.add_job(
            with_app_context(self._github_auto_pull),
            trigger=IntervalTrigger(hours=12),
            id="agent_github_auto_pull",
            name="Agent Loop: GitHub Auto-Pull & Re-Index",
            replace_existing=True,
        )

        # Job #56 — Skill analyzer: AI-powered quality scoring for discovered skills
        self.scheduler.add_job(
            with_app_context(self._analyze_discovered_skills),
            trigger=IntervalTrigger(hours=6, start_date="2026-01-01 01:00:00"),
            id="agent_skill_analyzer",
            name="Agent Loop: Skill Analyzer (Bridge AI)",
            replace_existing=True,
        )

        # Job #57 — Compliance scan: STIG rule evaluation every 6 hours
        self.scheduler.add_job(
            with_app_context(self._run_scheduled_compliance_scan),
            trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:00:00"),
            id="agent_compliance_scan",
            name="Agent Loop: Compliance Scan",
            replace_existing=True,
        )

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

        # Job #58 — Auto-remediation: fix low-risk compliance failures 30min after scan
        self.scheduler.add_job(
            with_app_context(self._run_auto_remediation),
            trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:30:00"),
            id="agent_auto_remediation",
            name="Agent Loop: Compliance Auto-Remediation",
            replace_existing=True,
        )

        # --- Migrated from consciousness_scheduler (APScheduler in app.py) ---

        # Conversation consolidation (hourly)
        self.scheduler.add_job(
            with_app_context(self._conversation_consolidation),
            trigger=IntervalTrigger(hours=1),
            id="agent_conversation_consolidation",
            name="Agent Loop: Conversation Consolidation",
            replace_existing=True,
        )

        # Improvement detection (every 6h)
        self.scheduler.add_job(
            with_app_context(self._improvement_detection),
            trigger=IntervalTrigger(hours=6),
            id="agent_improvement_detection",
            name="Agent Loop: Improvement Detection",
            replace_existing=True,
        )

        # Daily self-reflection (midnight)
        self.scheduler.add_job(
            with_app_context(self._daily_self_reflection),
            trigger=CronTrigger(hour=0, minute=0),
            id="agent_daily_self_reflection",
            name="Agent Loop: Daily Self-Reflection",
            replace_existing=True,
        )

        # Weekly memory consolidation (Sunday 3 AM)
        self.scheduler.add_job(
            with_app_context(self._weekly_memory_consolidation),
            trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
            id="agent_weekly_memory_consolidation",
            name="Agent Loop: Weekly Memory Consolidation",
            replace_existing=True,
        )

        # --- Migrated from infrastructure scheduler (app.py) ---

        # Batch medium issues (Sunday 2 AM)
        self.scheduler.add_job(
            with_app_context(self._batch_medium_issues),
            trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
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
            trigger=CronTrigger(day_of_week="sun", hour=4, minute=0),
            id="agent_weekly_dependency_scan",
            name="Agent Loop: Weekly Dependency Scan",
            replace_existing=True,
        )

        # Health probe (every 15 min)
        self.scheduler.add_job(
            with_app_context(self._health_probe),
            trigger=IntervalTrigger(minutes=15),
            id="agent_health_probe",
            name="Agent Loop: Service Health Probe",
            replace_existing=True,
        )

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

        # Job #59 — Standalone health monitoring: ping KSM every 60s, alert on downtime
        self.scheduler.add_job(
            with_app_context(self._check_standalone_health),
            trigger=IntervalTrigger(seconds=60),
            id="agent_standalone_health",
            name="Agent Loop: Standalone Health Monitor",
            replace_existing=True,
        )

        # Job #60 — Department metrics rollup: daily at 2:00 AM, owned by S.P.E.C.T.R.A.
        self.scheduler.add_job(
            with_app_context(self._department_metrics_rollup),
            trigger=CronTrigger(hour=2, minute=0),
            id="department_metrics_rollup",
            name="Agent Loop: Department Metrics Rollup",
            replace_existing=True,
        )

        # Job #61: Fleet SSL wildcard cert renewal (daily 03:00 UTC)
        self.scheduler.add_job(
            with_app_context(self._renew_fleet_ssl),
            trigger=CronTrigger(hour=3, minute=0),
            id="fleet_ssl_renewal",
            name="Agent Loop: Fleet SSL Renewal",
            replace_existing=True,
        )

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

        self._running = True
        logger.info("Agent loop started with 64 jobs")

    def _update_stock_prices(self):
        """Job #27: Refresh cached stock prices, check price alerts, and auto-scan watchlist every 5 minutes."""
        try:
            from database import get_db_cursor
            from tools.stockbot.services.market_data_service import batch_update_prices
            from tools.stockbot.services.portfolio_service import check_alerts

            # Gather all tickers currently being watched or held
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT DISTINCT ticker FROM stock_watchlist "
                    "UNION SELECT DISTINCT ticker FROM stock_portfolio WHERE shares > 0"
                )
                rows = cur.fetchall()

            tickers = [r[0] for r in rows]
            if tickers:
                updated = batch_update_prices(tickers)
                triggered = check_alerts()
                logger.debug(
                    f"Stock price updater: refreshed {updated}/{len(tickers)} tickers, "
                    f"triggered {triggered} alerts"
                )

            # Phase 2: Auto-scan watchlist for stale AI analyses (cap 5/cycle, 4h TTL)
            try:
                from tools.stockbot.services.stock_analysis_service import auto_scan_watchlist

                scanned = auto_scan_watchlist()
                if scanned:
                    logger.info(f"Stock auto-scan: ran analysis on {scanned} watchlist ticker(s)")
            except Exception as scan_err:
                logger.error(f"auto_scan_watchlist error: {scan_err}")

            # Phase 3: Evaluate automated trading strategies
            try:
                from tools.stockbot.services.strategy_service import evaluate_strategies

                evaluated = evaluate_strategies()
                if evaluated:
                    logger.info(f"Stock strategy evaluator: processed {evaluated} active strategy/strategies")
            except Exception as strat_err:
                logger.error(f"evaluate_strategies error: {strat_err}")

            # Phase 4: Sentiment scan for top 3 watchlist tickers
            try:
                from tools.stockbot.services.sentiment_service import analyze_sentiment

                top_tickers = tickers[:3] if tickers else []
                for t in top_tickers:
                    try:
                        analyze_sentiment(t)
                    except Exception:
                        pass
                if top_tickers:
                    logger.debug(f"Stock sentiment scan: updated {len(top_tickers)} ticker(s)")
            except Exception as sent_err:
                logger.error(f"sentiment_scan error: {sent_err}")

        except Exception as e:
            logger.error(f"_update_stock_prices error: {e}")

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

    def _compute_media_analytics(self):
        """Compute hourly analytics snapshots. Also daily at midnight."""
        from datetime import datetime
        from tools.media_studio.services.analytics_service import compute_snapshot
        try:
            count = compute_snapshot(period_type='hourly')
            logger.info(f"[Analytics] Hourly: {count} snapshots")
            if datetime.utcnow().hour == 0:
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

            if datetime.utcnow().hour == 18:
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
        """Job #28: Find and merge duplicate/overlapping knowledge entries."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                # Find entries with very similar titles (potential duplicates)
                cur.execute("""
                    SELECT a.id as id1, b.id as id2, a.title as title1, b.title as title2
                    FROM knowledge_base a
                    JOIN knowledge_base b ON a.id < b.id
                    WHERE a.is_archived = false AND b.is_archived = false
                    AND a.category = b.category
                    AND similarity(a.title, b.title) > 0.7
                    LIMIT 20
                """)
                dupes = cur.fetchall()

                for dupe in dupes:
                    # Keep the one with higher importance, archive the other
                    cur.execute("""
                        UPDATE knowledge_base SET is_archived = true
                        WHERE id = (
                            SELECT id FROM knowledge_base
                            WHERE id IN (%s, %s)
                            ORDER BY importance ASC, created_at ASC
                            LIMIT 1
                        )
                    """, (dupe['id1'], dupe['id2']))

                if dupes:
                    logger.info(f"[Knowledge] Archived {len(dupes)} duplicate entries")
        except Exception as e:
            logger.error(f"[Knowledge] Deduplication error: {e}")

    def _index_claude_sessions(self):
        """Job #29: Index recent Claude conversation sessions into knowledge_base."""
        try:
            from services.session_indexer_service import index_recent_sessions

            count = index_recent_sessions(max_sessions=5)
            if count > 0:
                logger.info(f"[Sessions] Indexed {count} Claude sessions")
        except Exception as e:
            logger.error(f"[Sessions] Indexing error: {e}")

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

        except Exception as e:
            logger.error(f"Proactive scan job failed: {e}")

    # ------------------------------------------------------------------
    # HR Tracker (Project #91 — Phase 7)
    # ------------------------------------------------------------------

    def _run_ethics_monitoring(self):
        """Run C.R.E.E.D. ethics monitoring cycle (every 15 min).

        Managed by V.I.G.I.L. (Security & Compliance director).
        Results visible in Department HQ + C.R.E.E.D. institute page.
        """
        start = time.time()
        try:
            from ai_bridge.ethics_monitor import EthicsMonitor
            monitor = EthicsMonitor()
            result = monitor.run_full_monitoring_cycle()
            duration_ms = int((time.time() - start) * 1000)
            checked = getattr(result, 'agents_checked', 0) if result else 0
            issues = getattr(result, 'issues_found', 0) if result else 0
            alerts = getattr(result, 'alerts_created', 0) if result else 0
            if issues > 0 or alerts > 0:
                logger.info(f"C.R.E.E.D. ethics: {checked} checked, "
                           f"{issues} issues, {alerts} alerts")
            self._log_cycle("ethics_monitoring", checked, issues, duration_ms,
                           details={"issues": issues, "alerts": alerts})
        except Exception as e:
            logger.error(f"C.R.E.E.D. ethics monitoring failed: {e}")
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("ethics_monitoring", 0, 1, duration_ms, error_message=str(e))

    # ------------------------------------------------------------------
    # Migrated from consciousness_scheduler (centralized into Autonomy)
    # ------------------------------------------------------------------

    def _conversation_consolidation(self):
        """Hourly conversation consolidation — migrated from consciousness_scheduler."""
        start = time.time()
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from consciousness_scheduler import hourly_conversation_consolidation
            result = hourly_conversation_consolidation()
            duration_ms = int((time.time() - start) * 1000)
            processed = result.get("messages_processed", 0) if isinstance(result, dict) else 0
            self._log_cycle("conversation_consolidation", processed, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("conversation_consolidation", 0, 1, duration_ms, error_message=str(e))

    def _improvement_detection(self):
        """Improvement detection every 6h — migrated from consciousness_scheduler."""
        start = time.time()
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from consciousness_scheduler import improvement_detection
            result = improvement_detection()
            duration_ms = int((time.time() - start) * 1000)
            found = result.get("improvements_found", 0) if isinstance(result, dict) else 0
            self._log_cycle("improvement_detection", found, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("improvement_detection", 0, 1, duration_ms, error_message=str(e))

    def _daily_self_reflection(self):
        """Daily self-reflection at midnight — migrated from consciousness_scheduler."""
        start = time.time()
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from consciousness_scheduler import daily_self_reflection
            result = daily_self_reflection()
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("daily_self_reflection", 1, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("daily_self_reflection", 0, 1, duration_ms, error_message=str(e))

    def _weekly_memory_consolidation(self):
        """Weekly memory consolidation (Sun 3AM) — migrated from consciousness_scheduler."""
        start = time.time()
        try:
            import sys
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
            from consciousness_scheduler import weekly_memory_consolidation
            result = weekly_memory_consolidation()
            duration_ms = int((time.time() - start) * 1000)
            decayed = result.get("memories_decayed", 0) if isinstance(result, dict) else 0
            self._log_cycle("weekly_memory_consolidation", decayed, 0, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("weekly_memory_consolidation", 0, 1, duration_ms, error_message=str(e))

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
            from tools.consciousness.routes import _store_dependency_scan
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
                    if endpoint == "embed":
                        data = {"model": model_name, "input": "health", "keep_alive": -1}
                    else:
                        opts = {"num_predict": 1}
                        if not use_gpu:
                            opts["num_gpu"] = 0
                        data = {"model": model_name, "prompt": "health", "stream": False, "options": opts, "keep_alive": -1}
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
            from ai_bridge.bridge_dispatcher import get_dispatcher
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
        """Discover new network devices via AdGuard + ARP (every 5 min)."""
        try:
            from tools.security_network.device_registry_service import DeviceRegistryService
            from tools.security_network.security_alerts import create_security_alert

            svc = DeviceRegistryService()
            new_devices = svc.discover_devices()

            for device in new_devices:
                ip = device.get("ip_address", "?")
                mac = device.get("mac_address", "?")
                mfr = device.get("manufacturer", "Unknown")
                create_security_alert(
                    "new_device",
                    f"New device detected: {mfr}",
                    f"IP: {ip} | MAC: {mac} | Manufacturer: {mfr}",
                    priority="high",
                    telegram=True,
                )

            if new_devices:
                logger.info(f"Network discovery: {len(new_devices)} new devices found")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _track_agent_hr(self):
        """
        Aggregate task_execution_log into agent_daily_summary.
        Check for overwork, high error rates, and idle agents.
        Create alerts and send Telegram notifications for critical issues.
        Runs every 5 minutes.
        """
        start = time.time()
        processed = 0
        alerts_created = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if not self._is_enabled(cur, "hr_tracker_enabled"):
                cur.close()
                conn.close()
                return

            today = datetime.utcnow().date()

            # 1. Aggregate today's task_execution_log into agent_daily_summary
            cur.execute("""
                SELECT agent_id,
                       COUNT(*) as total_tasks,
                       COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                       COUNT(CASE WHEN success = FALSE THEN 1 END) as failed,
                       COALESCE(SUM(duration_ms), 0) as total_duration,
                       COALESCE(AVG(duration_ms), 0) as avg_duration,
                       ARRAY_AGG(DISTINCT model_used) FILTER (WHERE model_used IS NOT NULL) as models,
                       ARRAY_AGG(DISTINCT module_source) FILTER (WHERE module_source IS NOT NULL) as modules,
                       ARRAY_AGG(DISTINCT capability) FILTER (WHERE capability IS NOT NULL) as capabilities
                FROM task_execution_log
                WHERE created_at::date = %s AND agent_id IS NOT NULL
                GROUP BY agent_id
            """, (today,))
            agent_stats = cur.fetchall()

            for stat in agent_stats:
                error_rate = 0
                if stat["total_tasks"] > 0:
                    error_rate = round(
                        (stat["failed"] / stat["total_tasks"]) * 100, 2
                    )

                # Calculate utilization: tasks * avg_duration / 5min window
                # Simplified: fraction of time spent on tasks in the day so far
                hours_elapsed = max(
                    (datetime.utcnow() - datetime.combine(today, datetime.min.time())).total_seconds() / 3600,
                    0.1,
                )
                work_hours = stat["total_duration"] / 3_600_000  # ms → hours
                utilization = min(round((work_hours / hours_elapsed) * 100, 2), 100)

                cur.execute("""
                    INSERT INTO agent_daily_summary
                    (agent_id, summary_date, total_tasks, successful_tasks, failed_tasks,
                     total_duration_ms, avg_duration_ms, models_used, modules_served,
                     capabilities_used, utilization_pct, error_rate_pct, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (agent_id, summary_date) DO UPDATE SET
                        total_tasks = EXCLUDED.total_tasks,
                        successful_tasks = EXCLUDED.successful_tasks,
                        failed_tasks = EXCLUDED.failed_tasks,
                        total_duration_ms = EXCLUDED.total_duration_ms,
                        avg_duration_ms = EXCLUDED.avg_duration_ms,
                        models_used = EXCLUDED.models_used,
                        modules_served = EXCLUDED.modules_served,
                        capabilities_used = EXCLUDED.capabilities_used,
                        utilization_pct = EXCLUDED.utilization_pct,
                        error_rate_pct = EXCLUDED.error_rate_pct,
                        updated_at = NOW()
                """, (
                    stat["agent_id"], today, stat["total_tasks"],
                    stat["successful"], stat["failed"],
                    stat["total_duration"], round(float(stat["avg_duration"]), 1),
                    stat["models"] or [], stat["modules"] or [],
                    stat["capabilities"] or [], utilization, error_rate,
                ))
                processed += 1

            # 2. Check for alert conditions

            # 2a. High error rate (>30% with at least 5 tasks)
            cur.execute("""
                SELECT ads.agent_id, a.name, ads.error_rate_pct, ads.total_tasks
                FROM agent_daily_summary ads
                JOIN agents a ON a.id = ads.agent_id
                WHERE ads.summary_date = %s
                  AND ads.error_rate_pct > 30
                  AND ads.total_tasks >= 5
            """, (today,))
            for row in cur.fetchall():
                alerts_created += self._create_hr_alert(
                    cur, row["agent_id"],
                    "high_error_rate", "warning",
                    f"{row['name']}: {row['error_rate_pct']}% error rate",
                    f"Agent {row['name']} has a {row['error_rate_pct']}% error rate "
                    f"across {row['total_tasks']} tasks today.",
                    {"error_rate": float(row["error_rate_pct"]),
                     "total_tasks": row["total_tasks"]},
                )

            # 2b. Overwork: >8h continuous work (total_duration_ms > 28800000)
            cur.execute("""
                SELECT ads.agent_id, a.name, ads.total_duration_ms
                FROM agent_daily_summary ads
                JOIN agents a ON a.id = ads.agent_id
                WHERE ads.summary_date = %s
                  AND ads.total_duration_ms > 28800000
            """, (today,))
            for row in cur.fetchall():
                hours = round(row["total_duration_ms"] / 3_600_000, 1)
                alerts_created += self._create_hr_alert(
                    cur, row["agent_id"],
                    "overwork", "critical",
                    f"{row['name']}: {hours}h continuous work",
                    f"Agent {row['name']} has worked {hours} hours today. "
                    f"Consider initiating a rest cycle.",
                    {"work_hours": hours},
                )

                # Auto-initiate rest cycle for overworked agents
                cur.execute("""
                    INSERT INTO agent_rest_cycles
                    (agent_id, reason, started_at)
                    SELECT %s, 'Automatic rest: exceeded 8h work threshold', NOW()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM agent_rest_cycles
                        WHERE agent_id = %s
                          AND started_at > NOW() - INTERVAL '1 hour'
                    )
                """, (row["agent_id"], row["agent_id"]))

            # 2c. Update emotional state based on workload
            cur.execute("""
                SELECT ads.agent_id, ads.utilization_pct, ads.error_rate_pct
                FROM agent_daily_summary ads
                WHERE ads.summary_date = %s
            """, (today,))
            for row in cur.fetchall():
                stress = min(float(row["utilization_pct"]) / 100, 1.0)
                energy = max(1.0 - stress * 0.5 - float(row["error_rate_pct"]) / 200, 0.1)
                mood = "stressed" if stress > 0.8 else "focused" if stress > 0.4 else "relaxed"

                update_welfare(
                    row["agent_id"],
                    stress=round(stress, 2),
                    energy=round(energy, 2),
                    mood=mood,
                )

            conn.commit()

            # 2d. Check proficiency degradation (fail too much → degrade → auto-train)
            degraded = self._check_proficiency_degradation(cur, conn)
            alerts_created += degraded

            conn.commit()

            # 3. Send Telegram alerts for critical issues
            self._send_hr_telegram_alerts(cur, conn)

            conn.commit()
            cur.close()
            conn.close()

            duration_ms = int((time.time() - start) * 1000)
            if processed > 0 or alerts_created > 0:
                logger.info(
                    f"HR tracker: {processed} agents updated, "
                    f"{alerts_created} alerts created ({duration_ms}ms)"
                )
            self._log_cycle(
                "hr_tracker", processed, 0, duration_ms,
                {"alerts_created": alerts_created},
            )

        except Exception as e:
            logger.error(f"HR tracker failed: {e}")
            self._log_cycle("hr_tracker", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

    def _recover_idle_welfare(self):
        """
        Recover welfare for idle and resting agents.
        Runs every 30 minutes.
        - Idle (not dispatched in last hour): stress -0.15, energy +0.2
        - Resting (active rest cycle): stress -0.3, energy +0.4
        """
        start = time.time()
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            if not self._is_enabled(cur, "hr_tracker_enabled"):
                cur.close()
                conn.close()
                return

            # Find agents with recent dispatches (last hour)
            cur.execute("""
                SELECT DISTINCT agent_name FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """)
            busy_names = {r["agent_name"] for r in cur.fetchall()}

            # Find resting agents
            cur.execute("""
                SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
            """)
            resting_ids = {r["agent_id"] for r in cur.fetchall()}

            # Get all active agents with current welfare
            cur.execute("""
                SELECT DISTINCT ON (a.id)
                       a.id, a.name, es.stress_level, es.energy_level
                FROM agents a
                LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
                WHERE a.status = 'active'
                ORDER BY a.id, es.timestamp DESC NULLS LAST
            """)
            agents = cur.fetchall()

            recovered = 0
            for agent in agents:
                aid = agent["id"]
                name = agent["name"]
                stress = float(agent["stress_level"] or 0.2)
                energy = float(agent["energy_level"] or 0.8)

                if aid in resting_ids:
                    # Resting: faster recovery
                    new_stress = max(0.0, stress - 0.3)
                    new_energy = min(1.0, energy + 0.4)
                elif name not in busy_names:
                    # Idle: moderate recovery
                    new_stress = max(0.0, stress - 0.15)
                    new_energy = min(1.0, energy + 0.2)
                else:
                    continue  # Active agent, skip

                if new_stress == stress and new_energy == energy:
                    continue  # No change needed

                cur.execute("""
                    INSERT INTO agent_emotional_state
                    (agent_id, stress_level, energy_level, current_mood, trigger_event, timestamp)
                    VALUES (%s, %s, %s,
                            CASE WHEN %s < 0.3 THEN 'relaxed'
                                 WHEN %s < 0.6 THEN 'neutral'
                                 ELSE 'focused' END,
                            'welfare_recovery', NOW())
                """, (aid, new_stress, new_energy, new_stress, new_stress))
                recovered += 1

            conn.commit()
            duration_ms = int((time.time() - start) * 1000)
            if recovered > 0:
                logger.info(f"Welfare recovery: updated {recovered} agents")
            self._log_cycle(
                "welfare_recovery", recovered, 0, duration_ms,
                {"busy_agents": len(busy_names), "resting_agents": len(resting_ids)},
            )
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Welfare recovery error: {e}")
            self._log_cycle("welfare_recovery", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

    def _volunteer_idle_agents(self):
        """
        Scan for idle agents and volunteer them at departments with pending work.
        Runs every 5 minutes.
        - Find departments with recent task failures
        - Find idle agents not in those departments
        - Create notifications for volunteering events
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            start = time.time()

            # Find departments with recent failures and no idle primaries
            cur.execute("""
                SELECT a.department,
                       COUNT(*) AS recent_failures
                FROM task_execution_log tel
                JOIN agents a ON tel.agent_name = a.name
                WHERE tel.success = FALSE
                  AND tel.created_at > NOW() - INTERVAL '30 minutes'
                  AND a.department IS NOT NULL
                GROUP BY a.department
                ORDER BY recent_failures DESC
                LIMIT 5
            """)
            pending_jobs = cur.fetchall()

            if not pending_jobs:
                cur.close()
                conn.close()
                return

            # Find idle agents (not busy, not resting, active status)
            cur.execute("""
                SELECT a.id, a.name, a.model,
                       a.department AS home_department
                FROM agents a
                LEFT JOIN bridge_jobs bj ON bj.agent_name = a.name AND bj.status = 'running'
                LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
                WHERE a.status = 'active'
                  AND bj.id IS NULL
                  AND arc.id IS NULL
                  AND a.shift_state IN ('active', 'winding_down')
                  AND a.department IS NOT NULL
            """)
            idle_agents = cur.fetchall()

            if not idle_agents:
                cur.close()
                conn.close()
                return

            volunteered = 0
            for job in pending_jobs:
                # Find an idle agent NOT from this department
                volunteer = None
                for agent in idle_agents:
                    if agent["home_department"] != job["department"]:
                        volunteer = agent
                        break

                if volunteer:
                    logger.info(
                        f"Volunteering {volunteer['name']} from {volunteer['home_department']} "
                        f"to help {job['department']} ({job['recent_failures']} recent failures)"
                    )
                    self._create_notification(
                        f"Fleet: {volunteer['name']} volunteering at {job['department']}",
                        "info",
                        {"agent": volunteer["name"], "department": job["department"]},
                    )
                    volunteered += 1
                    # Remove from idle list so they don't get double-assigned
                    idle_agents = [a for a in idle_agents if a["id"] != volunteer["id"]]

            conn.commit()
            duration_ms = int((time.time() - start) * 1000)
            if volunteered > 0:
                logger.info(f"Idle volunteering: {volunteered} agents offered")
                self._log_cycle("idle_volunteering", volunteered, 0, duration_ms, f"{volunteered} agents volunteered")
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Idle volunteering error: {e}")

    def _update_performance_rankings(self):
        """
        Calculate comparative performance rankings per capability.
        Runs every 15 minutes.
        rank_score = (success_rate * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)
        Minimum 10 tasks for reliable ranking — below that, blend static proficiency.
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            start = time.time()

            # Get per-agent-per-capability stats (last 30 days)
            cur.execute("""
                SELECT agent_id, capability,
                       COUNT(*) AS tasks_completed,
                       AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                       AVG(duration_ms) AS avg_duration_ms,
                       AVG(tokens_used) AS avg_tokens_used
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '30 days'
                  AND agent_id IS NOT NULL
                  AND capability IS NOT NULL
                GROUP BY agent_id, capability
            """)
            stats = cur.fetchall()

            if not stats:
                cur.close()
                conn.close()
                return

            # Group by capability for comparative scoring
            by_capability = {}
            for row in stats:
                cap = row["capability"]
                if cap not in by_capability:
                    by_capability[cap] = []
                by_capability[cap].append(row)

            updated = 0
            for capability, agents in by_capability.items():
                max_duration = max(float(a["avg_duration_ms"] or 1) for a in agents)
                max_tokens = max(float(a["avg_tokens_used"] or 1) for a in agents)

                scored = []
                for agent in agents:
                    sr = float(agent["success_rate"] or 0)
                    duration = float(agent["avg_duration_ms"] or 0)
                    tokens = float(agent["avg_tokens_used"] or 0)
                    sample = int(agent["tasks_completed"] or 0)

                    speed_score = 1.0 - (duration / max_duration) if max_duration > 0 else 0.5
                    efficiency_score = 1.0 - (tokens / max_tokens) if max_tokens > 0 else 0.5

                    rank_score = (sr * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)

                    # Blend with static proficiency if sample too small
                    if sample < 10:
                        cur.execute("""
                            SELECT proficiency_level FROM agent_skills
                            WHERE agent_id = %s AND skill_name = %s
                        """, (agent["agent_id"], capability))
                        skill_row = cur.fetchone()
                        static_prof = float(skill_row["proficiency_level"] or 3) / 5.0 if skill_row else 0.5
                        rank_score = (static_prof * 0.7) + (rank_score * 0.3)

                    scored.append({
                        **agent,
                        "rank_score": round(rank_score, 4),
                    })

                scored.sort(key=lambda x: x["rank_score"], reverse=True)
                for position, agent in enumerate(scored, 1):
                    cur.execute("""
                        INSERT INTO agent_performance_rankings
                        (agent_id, capability, tasks_completed, success_rate,
                         avg_duration_ms, avg_tokens_used, rank_score, rank_position,
                         sample_size, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (agent_id, capability)
                        DO UPDATE SET
                            tasks_completed = EXCLUDED.tasks_completed,
                            success_rate = EXCLUDED.success_rate,
                            avg_duration_ms = EXCLUDED.avg_duration_ms,
                            avg_tokens_used = EXCLUDED.avg_tokens_used,
                            rank_score = EXCLUDED.rank_score,
                            rank_position = EXCLUDED.rank_position,
                            sample_size = EXCLUDED.sample_size,
                            last_updated = NOW()
                    """, (
                        agent["agent_id"], capability,
                        agent["tasks_completed"], agent["success_rate"],
                        agent["avg_duration_ms"], agent["avg_tokens_used"],
                        agent["rank_score"], position,
                        agent["tasks_completed"],
                    ))
                    updated += 1

            conn.commit()
            duration_ms = int((time.time() - start) * 1000)
            if updated > 0:
                logger.info(f"Performance rankings: updated {updated} entries across {len(by_capability)} capabilities")
                self._log_cycle("performance_rankings", updated, 0, duration_ms, f"Updated {updated} entries")
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Performance ranking error: {e}")

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
                    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
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
                        from ai_bridge.bridge_dispatcher import get_dispatcher
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
        """Check for completed training assignments and finalize them.

        When target_completion is reached:
        - Mark training as completed
        - Restore/boost confidence in agent_learning_log
        - Store failure_analysis as knowledge_base entry
        - Nudge emotional state positively
        - Send Telegram notification
        """
        start = time.time()
        completed = 0

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Find training assignments that have reached their target_completion
            cur.execute("""
                SELECT ta.id, ta.agent_id, ta.skill_name, ta.target_proficiency,
                       ta.current_proficiency, ta.failure_analysis, ta.degradation_triggered,
                       a.name as agent_name,
                       COALESCE(a.display_name, a.first_name || ' ' || a.last_name) as display_name
                FROM training_assignments ta
                JOIN agents a ON a.id = ta.agent_id
                WHERE ta.status = 'in_progress'
                  AND ta.target_completion IS NOT NULL
                  AND ta.target_completion <= NOW()
            """)
            ready = cur.fetchall()

            for t in ready:
                agent_id = t["agent_id"]
                skill_name = t["skill_name"]
                target_level = t["target_proficiency"]
                display_name = t["display_name"] or t["agent_name"]

                # Mark training as completed
                cur.execute("""
                    UPDATE training_assignments
                    SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                """, (t["id"],))

                # Advance agent's proficiency level to target
                add_skill(agent_id, skill_name, level=target_level)

                # Boost confidence in agent_learning_log (cap at 1.0)
                cur.execute("""
                    UPDATE agent_learning_log
                    SET confidence = LEAST(1.0, confidence + 0.15),
                        successful_uses = successful_uses + 1,
                        last_used_at = NOW()
                    WHERE agent_id = %s AND skill_name = %s
                """, (agent_id, skill_name))

                # Store failure_analysis as knowledge_base entry for future reference
                if t["failure_analysis"]:
                    cur.execute("""
                        INSERT INTO knowledge_base
                        (title, content, source_type, tags, category, is_active, created_at)
                        VALUES (%s, %s, 'agent_learning', %s, 'training', TRUE, NOW())
                    """, (
                        f"Training Completion: {display_name} - {skill_name} Lv{target_level}",
                        f"Agent: {display_name}\nSkill: {skill_name}\nTarget Level: {target_level}\n\n"
                        f"Failure Analysis & Corrections:\n{t['failure_analysis']}",
                        json.dumps([t["agent_name"], skill_name, "training-completion"]),
                    ))

                # Nudge emotional state positively
                recover_idle(agent_id, energy_boost=0.1, stress_reduction=0.1)

                completed += 1
                logger.info(
                    f"Training completed: {display_name} finished {skill_name} "
                    f"training, advanced to Lv{target_level}"
                )

            if completed > 0:
                conn.commit()

                # Send Telegram notification for completions
                try:
                    gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
                    if gateway and gateway.is_running:
                        cur.execute("""
                            SELECT telegram_id FROM telegram_users
                            WHERE is_authorized = TRUE AND user_id IS NOT NULL LIMIT 1
                        """)
                        tg_user = cur.fetchone()
                        if tg_user:
                            import asyncio
                            loop = gateway._loop
                            for t in ready:
                                dn = t["display_name"] or t["agent_name"]
                                text = (
                                    f"\U0001f393 *Training Complete*\n\n"
                                    f"{dn} finished {t['skill_name']} training, "
                                    f"now at Lv{t['target_proficiency']}."
                                )
                                asyncio.run_coroutine_threadsafe(
                                    gateway._application.bot.send_message(
                                        chat_id=tg_user["telegram_id"],
                                        text=text, parse_mode="Markdown",
                                    ),
                                    loop,
                                )
                except Exception as e:
                    logger.warning(f"Failed: {e}")

            cur.close()
            conn.close()

            duration_ms = int((time.time() - start) * 1000)
            if completed > 0:
                logger.info(f"Training tick: {completed} trainings completed ({duration_ms}ms)")
            self._log_cycle("training_tick", completed, 0, duration_ms)

        except Exception as e:
            logger.error(f"Training tick failed: {e}")
            self._log_cycle("training_tick", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

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
        department = JOB_DEPARTMENT_MAP.get(job_name, "Operations & Infrastructure")
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
            logger.error(f"Failed to log agent cycle: {e}")

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
        """Weekly security configuration audit — verify nothing has drifted."""
        try:
            from tools.security_network.security_alerts import create_security_alert
            import subprocess

            issues = []

            # 1. Check SSH config
            try:
                r = subprocess.run(
                    ["cat", "/etc/ssh/sshd_config.d/99-archie-hardening.conf"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "PasswordAuthentication no" not in r.stdout:
                    issues.append("SSH password auth may be enabled")
            except Exception:
                issues.append("Cannot read SSH hardening config")

            # 2. Check fail2ban
            try:
                import socket

                # Check if fail2ban log exists (proxy for service running)
                r = subprocess.run(
                    ["test", "-f", "/var/log/fail2ban.log"],
                    capture_output=True,
                    timeout=5,
                )
                # Just check the file exists as a proxy
            except Exception:
                pass

            # 3. Check UFW rules for PostgreSQL
            try:
                r = subprocess.run(
                    ["cat", "/etc/ufw/user.rules"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if (
                    "5432" in r.stdout
                    and "Anywhere" in r.stdout
                    and "192.168.1.0/24" not in r.stdout
                ):
                    issues.append("PostgreSQL port 5432 may be exposed to internet")
            except Exception:
                pass

            # 4. Check DDNS updater freshness
            import os
            import time

            ddns_file = "/mnt/archie_brain/scripts/.ddns_last_ip"
            if os.path.exists(ddns_file):
                age_hours = (time.time() - os.path.getmtime(ddns_file)) / 3600
                if age_hours > 1:
                    issues.append(
                        f"DDNS updater hasn't run in {age_hours:.0f} hours"
                    )
            else:
                issues.append("DDNS updater IP file missing")

            # 5. Check AdGuard protection
            try:
                import requests

                host = os.getenv("ADGUARD_HOST", "network_adguard")
                port = os.getenv("ADGUARD_PORT", "80")
                user = os.getenv("ADGUARD_USER", "")
                pw = os.getenv("ADGUARD_PASS", "")
                r = requests.get(
                    f"http://{host}:{port}/control/status",
                    auth=(user, pw),
                    timeout=5,
                )
                if not r.json().get("protection_enabled"):
                    issues.append("AdGuard DNS protection is disabled")
            except Exception:
                issues.append("Cannot reach AdGuard")

            if issues:
                create_security_alert(
                    "scan_result",
                    f"Security audit: {len(issues)} issue(s) found",
                    "Issues:\n" + "\n".join(f"• {i}" for i in issues),
                    priority="high",
                    telegram=True,
                )
                logger.warning(f"Security audit: {len(issues)} issues: {issues}")
            else:
                logger.info("Security audit: all checks passed")

        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _run_scheduled_compliance_scan(self):
        """Job #57: Run STIG compliance scan every 6 hours + auto-collect SOC 2 evidence."""
        try:
            from tools.security_network.compliance_service import (
                run_scan,
                collect_evidence,
            )

            result = run_scan(triggered_by="scheduled")
            score = result.get("score", 0)
            scan_id = result.get("scan_id")
            logger.info(
                "Scheduled compliance scan complete: %.1f%% (%d/%d passed)",
                score,
                result.get("passed", 0),
                result.get("total", 0),
            )

            # Auto-collect SOC 2 evidence after each scan
            try:
                ev = collect_evidence(scan_id=scan_id)
                logger.info(
                    "SOC 2 evidence auto-collected: %d artifacts stored",
                    ev.get("stored", 0),
                )
            except Exception as ev_err:
                logger.warning("SOC 2 evidence collection failed: %s", ev_err)

            # Score change detection — notify on Telegram if score changed
            try:
                from database import get_db_cursor

                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """
                        SELECT score FROM compliance_scans
                        WHERE completed_at IS NOT NULL
                        ORDER BY started_at DESC LIMIT 2
                    """
                    )
                    rows = cur.fetchall()
                    if len(rows) >= 2:
                        new_score = float(rows[0]["score"])
                        old_score = float(rows[1]["score"])
                        if abs(new_score - old_score) >= 0.5:
                            direction = "\u2B06" if new_score > old_score else "\u2B07"
                            self._send_notification(
                                f"Compliance {direction} {old_score}% \u2192 {new_score}%",
                                "info"
                                if new_score >= old_score
                                else "warning",
                            )
            except Exception:
                pass  # Non-critical
        except Exception as e:
            logger.error("Scheduled compliance scan failed: %s", e)

    def _run_auto_remediation(self):
        """Job #58: Auto-fix low-risk compliance failures from the latest scan."""
        try:
            import json as _json
            from tools.security_network.compliance_service import (
                get_latest_scores,
                get_scan_results,
                apply_fix,
            )

            scores = get_latest_scores()
            if not scores or not scores.get("scan_id"):
                return

            scan_id = scores["scan_id"]
            results = get_scan_results(scan_id, status="fail")

            if not results:
                return

            # Build a lookup of rule_id -> fix risk from loaded rule packs
            from database import get_db_cursor

            risk_lookup = {}
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT pack_id, rules FROM compliance_rule_packs")
                for pack_row in cur.fetchall():
                    rules = (
                        pack_row["rules"]
                        if isinstance(pack_row["rules"], list)
                        else _json.loads(pack_row["rules"])
                    )
                    for rule in rules:
                        rid = rule.get("rule_id", "")
                        fix = rule.get("fix", {})
                        risk_lookup[rid] = fix.get("risk", "high")

            fixed = 0
            skipped = 0
            for result in results:
                rule_id = result.get("rule_id", "")
                risk = risk_lookup.get(rule_id, "high")

                # Only auto-fix low-risk rules (Tier 1 auto-approvable)
                if risk != "low":
                    skipped += 1
                    continue

                try:
                    fix_result = apply_fix(scan_id, rule_id, user_id=0)
                    if fix_result.get("success"):
                        fixed += 1
                        logger.info(
                            "Auto-remediation: fixed %s (risk=%s)", rule_id, risk
                        )
                    else:
                        logger.warning(
                            "Auto-remediation: failed to fix %s: %s",
                            rule_id,
                            fix_result.get("error", "unknown"),
                        )
                except Exception as fix_err:
                    logger.warning(
                        "Auto-remediation: error fixing %s: %s", rule_id, fix_err
                    )

            if fixed > 0 or skipped > 0:
                logger.info(
                    "Auto-remediation complete: %d fixed, %d skipped (non-low risk)",
                    fixed,
                    skipped,
                )
        except Exception as e:
            logger.error("Auto-remediation failed: %s", e)

    def _check_ssl_expiry(self):
        """Check SSL certificates for upcoming expiry (daily)."""
        try:
            from tools.security_network.npm_service import NPMService
            from tools.security_network.security_alerts import create_security_alert

            npm = NPMService()
            hosts = npm.list_proxy_hosts()
            if not hosts:
                return

            for host in hosts:
                cert_id = host.get("certificate_id")
                if not cert_id:
                    continue
                domain = (host.get("domain_names") or ["unknown"])[0]

                import ssl
                import socket
                from datetime import datetime

                try:
                    ctx = ssl.create_default_context()
                    with ctx.wrap_socket(
                        socket.socket(), server_hostname=domain
                    ) as s:
                        s.settimeout(5)
                        s.connect((domain, 443))
                        cert = s.getpeercert()
                        expiry = datetime.strptime(
                            cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
                        )
                        days_left = (expiry - datetime.utcnow()).days

                        if days_left <= 14:
                            priority = (
                                "critical"
                                if days_left <= 3
                                else "high"
                                if days_left <= 7
                                else "normal"
                            )
                            create_security_alert(
                                "ssl_expiry",
                                f"SSL cert expiring: {domain}",
                                f"Certificate for {domain} expires in {days_left} days ({expiry.strftime('%Y-%m-%d')})",
                                priority=priority,
                                telegram=True,
                            )
                            logger.warning(
                                f"SSL cert expiry: {domain} expires in {days_left} days"
                            )
                except Exception:
                    pass  # Can't check this domain

        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _daily_dns_report(self):
        """Generate daily DNS activity summary for Telegram (7 AM daily)."""
        try:
            import requests
            import os
            from tools.security_network.security_alerts import create_security_alert

            host = os.getenv("ADGUARD_HOST", "network_adguard")
            port = os.getenv("ADGUARD_PORT", "80")
            user = os.getenv("ADGUARD_USER", "")
            pw = os.getenv("ADGUARD_PASS", "")

            r = requests.get(
                f"http://{host}:{port}/control/stats",
                auth=(user, pw),
                timeout=10,
            )
            stats = r.json()

            queries = stats.get("num_dns_queries", 0)
            blocked = stats.get("num_blocked_filtering", 0)
            block_pct = round(blocked / queries * 100, 1) if queries > 0 else 0
            safe = stats.get("num_replaced_safebrowsing", 0)
            top_clients = stats.get("top_clients", [])[:3]
            top_blocked = stats.get("top_blocked_domains", [])[:3]

            client_lines = []
            for tc in top_clients:
                for ip, count in tc.items():
                    client_lines.append(f"  {ip}: {count}")

            blocked_lines = []
            for tb in top_blocked:
                for domain, count in tb.items():
                    blocked_lines.append(f"  {domain}: {count}")

            message = (
                f"Queries: {queries:,} | Blocked: {blocked:,} ({block_pct}%)\n"
                f"Safe browsing blocks: {safe}\n"
                f"Top clients:\n"
                + "\n".join(client_lines[:3])
                + "\n"
                f"Top blocked:\n" + "\n".join(blocked_lines[:3])
            )

            create_security_alert(
                "dns_change",
                "Daily DNS Report",
                message,
                priority="normal",
                telegram=True,
            )
            logger.info("Daily DNS report sent")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _detect_query_spike(self):
        """Detect unusual DNS query spikes (hourly)."""
        try:
            import requests
            import os
            from tools.security_network.security_alerts import create_security_alert

            host = os.getenv("ADGUARD_HOST", "network_adguard")
            port = os.getenv("ADGUARD_PORT", "80")
            user = os.getenv("ADGUARD_USER", "")
            pw = os.getenv("ADGUARD_PASS", "")

            r = requests.get(
                f"http://{host}:{port}/control/stats",
                auth=(user, pw),
                timeout=10,
            )
            stats = r.json()

            # Check if blocked queries are unusually high (>50% of total)
            queries = stats.get("num_dns_queries", 0)
            blocked = stats.get("num_blocked_filtering", 0)

            if queries > 100 and blocked > 0:
                block_rate = blocked / queries
                if block_rate > 0.5:
                    create_security_alert(
                        "scan_result",
                        f"DNS block rate spike: {block_rate:.0%}",
                        f"{blocked:,} blocked out of {queries:,} total queries ({block_rate:.0%}). Normal is <15%. Possible malware or misconfiguration.",
                        priority="high",
                        telegram=True,
                    )
                    logger.warning(
                        f"Query spike: {block_rate:.0%} blocked ({blocked}/{queries})"
                    )
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _check_camera_anomaly(self):
        """Alert if cameras have been offline or no motion detected in 4+ hours."""
        try:
            from tools.security_network.ha_surveillance_service import (
                HASurveillanceService,
            )
            from tools.security_network.security_alerts import create_security_alert

            svc = HASurveillanceService()
            if not svc.available:
                return

            cameras = svc.get_cameras()
            for cam in cameras:
                state = cam.get("state", "")
                name = cam.get("name", cam.get("entity_id", "unknown"))
                if state in ("unavailable", "unknown"):
                    create_security_alert(
                        "scan_result",
                        f"Camera offline: {name}",
                        f"Camera {name} ({cam.get('entity_id')}) is {state}",
                        priority="high",
                        telegram=True,
                    )
                    logger.warning(f"Camera anomaly: {name} is {state}")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _run_auto_block(self):
        """Run suggestion engine and auto-execute critical/high suggestions (every 15 min)."""
        try:
            from tools.security_network.agent_automation import AgentAutomationService
            from tools.security_network.security_alerts import create_security_alert

            svc = AgentAutomationService()
            if not svc.get_config().get("paused"):
                result = svc.generate_suggestions()
                if result and result.get("generated", 0) > 0:
                    logger.info(f"Auto-block: generated {result['generated']} suggestions")

                    # Auto-execute critical/high suggestions
                    pending = svc.get_pending_suggestions(limit=10)
                    for suggestion in pending:
                        data = suggestion.get("data", {})
                        if isinstance(data, str):
                            import json
                            try:
                                data = json.loads(data)
                            except (json.JSONDecodeError, TypeError):
                                data = {}
                        severity = data.get("severity", "low")
                        stype = data.get("suggestion_type", "")

                        if severity in ("critical", "high") and stype in (
                            "ssh_brute_force",
                            "device_vulnerability",
                        ):
                            try:
                                svc.approve_suggestion(suggestion["id"])
                                create_security_alert(
                                    "block",
                                    f"Auto-blocked: {suggestion.get('title', stype)}",
                                    suggestion.get("description", "Threat auto-blocked by security pipeline"),
                                    priority="high",
                                    telegram=True,
                                )
                                logger.info(
                                    f"Auto-block: executed suggestion #{suggestion['id']} ({stype})"
                                )
                            except Exception as e:
                                logger.warning(f"Failed: {e}")
        except Exception as e:
            logger.warning(f"Failed: {e}")

    def _daily_code_metrics_scan(self):
        """Job #40: Daily codebase metrics snapshot at 3:00 AM with stale audit detection."""
        start = time.time()
        try:
            from services.code_metrics_service import scan_and_detect_changes

            metrics, snapshot_id, changed_modules = scan_and_detect_changes()
            duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "Daily code metrics: %d files, %d lines (snapshot #%s, %d modules changed)",
                metrics["total_files"],
                metrics["total_lines"],
                snapshot_id,
                len(changed_modules),
            )
            self._log_cycle("code_metrics_scan", 1, 0, duration_ms)
        except Exception as e:
            self._log_cycle("code_metrics_scan", 0, 1, int((time.time() - start) * 1000), error_message=str(e))
            logger.warning(f"Failed: {e}")

    def _pattern_compliance_check(self):
        """Job #41: Scan for pattern violations at 4:00 AM."""
        try:
            import os
            import re
            from services.code_metrics_service import log_audit

            tools_dir = "/app/tools" if os.path.isdir("/app/tools") else "/mnt/archie_brain/platform_v2/tools"
            violations = []

            for root, dirs, files in os.walk(tools_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    filepath = os.path.join(root, fname)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()

                        # Check for direct Ollama calls (ADR-013 violation)
                        if "call_ollama(" in content and "bridge" not in filepath and "archie_bridge" not in filepath:
                            violations.append(f"DIRECT_OLLAMA: {filepath}")

                        # Check for call_claude_api / call_openai_api in modules
                        if ("call_claude_api(" in content or "call_openai_api(" in content) and "archie_bridge" not in filepath:
                            violations.append(f"DIRECT_CLOUD: {filepath}")

                    except Exception:
                        pass

            if violations:
                log_audit(
                    module_name="PATTERN_COMPLIANCE",
                    category="automated_scan",
                    issues_found=len(violations),
                    notes="; ".join(violations[:20]),
                    status="violations_found",
                )
                logger.warning("Pattern compliance: %d violations found", len(violations))
            self._log_cycle("pattern_compliance", len(violations), 0, 0)
        except Exception as e:
            self._log_cycle("pattern_compliance", 0, 1, 0, error_message=str(e))
            logger.warning(f"Failed: {e}")

    def _automated_module_audit(self):
        """Job #58: Automated module audit — weekly Sunday 3:30 AM."""
        try:
            from database import get_db_cursor
            from services.code_metrics_service import audit_single_module, log_audit
            from services.audit_pipeline import process_audit_findings

            # Load latest per_module data from most recent snapshot
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT per_module FROM code_metrics_snapshots
                       ORDER BY scanned_at DESC LIMIT 1"""
                )
                row = cur.fetchone()
                if not row or not row.get("per_module"):
                    logger.warning("Automated module audit: no snapshot found, skipping")
                    return

                per_module = row["per_module"]

                # Also check for open high/critical proposals per module
                cur.execute(
                    """SELECT title, COUNT(*) as cnt
                       FROM improvement_proposals
                       WHERE status NOT IN ('deployed', 'rejected', 'archived')
                         AND priority IN ('high', 'critical')
                       GROUP BY title"""
                )
                proposal_files = {r["title"]: r["cnt"] for r in cur.fetchall()}

            audited = 0
            clean = 0
            violations = 0
            severity_totals = {"red": 0, "yellow": 0, "info": 0}
            total_proposals = 0

            for module_name, stats in per_module.items():
                issues_found, notes, status, issues_list = audit_single_module(module_name)

                # Tally severity breakdown
                for issue in issues_list:
                    sev = issue.get("severity", "info")
                    severity_totals[sev] = severity_totals.get(sev, 0) + 1

                # Auto-generate Repair Bay proposals for red/yellow findings
                if issues_list:
                    try:
                        result = process_audit_findings(module_name, issues_list)
                        total_proposals += result.get("proposals_created", 0)
                    except Exception as pipe_err:
                        logger.warning(
                            "Audit pipeline failed for %s: %s", module_name, pipe_err
                        )

                # Check proposals affecting this module
                proposal_issues = 0
                module_clean = module_name.replace("_", " ").replace("-", " ").lower()
                for ptitle, cnt in proposal_files.items():
                    if module_clean in (ptitle or "").lower() or module_name in (ptitle or "").lower():
                        proposal_issues += cnt
                if proposal_issues > 0:
                    issues_found += proposal_issues
                    notes += f"; {proposal_issues} open high/critical proposals"
                    if status == "completed":
                        status = "violations_found"

                log_audit(
                    module_name=module_name,
                    category="automated_weekly",
                    files_reviewed=stats.get("files", 0),
                    lines_before=stats.get("lines", 0),
                    lines_after=stats.get("lines", 0),
                    issues_found=issues_found,
                    notes=notes,
                    status=status,
                )

                audited += 1
                if status == "completed":
                    clean += 1
                else:
                    violations += 1

            # --- Phase 1.5: Pre-dispatch model cleanup ---
            # Unload non-essential models to free VRAM/RAM for repair agents
            try:
                import urllib.request as _urllib
                essential_models = {"arctic-embed-cpu:latest", "qwen2.5-coder:7b", "qwen2.5:1.5b"}
                ps_resp = _urllib.urlopen("http://192.168.1.200:11434/api/ps", timeout=10)
                loaded = json.loads(ps_resp.read()).get("models", [])
                unloaded = 0
                for m in loaded:
                    if m["name"] not in essential_models:
                        try:
                            unload_data = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
                            unload_req = _urllib.Request(
                                "http://192.168.1.200:11434/api/generate",
                                data=unload_data,
                                headers={"Content-Type": "application/json"},
                            )
                            _urllib.urlopen(unload_req, timeout=30).read()
                            unloaded += 1
                        except Exception:
                            pass
                if unloaded:
                    logger.info("Repair pipeline: unloaded %d non-essential models before dispatch", unloaded)
            except Exception as cleanup_err:
                logger.debug("Pre-dispatch cleanup skipped: %s", cleanup_err)

            # --- Phase 2: Dispatch approved proposals for AI fixes ---
            try:
                from services.audit_pipeline import dispatch_audit_proposals
                dispatch_result = dispatch_audit_proposals(limit=10)
                total_dispatched = dispatch_result.get("dispatched", 0)
                logger.info(
                    "Repair pipeline phase 2: %d proposals dispatched for AI fixes",
                    total_dispatched,
                )
            except Exception as dispatch_err:
                logger.warning("Repair pipeline dispatch phase failed: %s", dispatch_err)
                total_dispatched = 0

            logger.info(
                "Automated module audit: %d modules audited (%d clean, %d violations) — "
                "severity: %d red, %d yellow, %d info — %d proposals created, %d dispatched",
                audited,
                clean,
                violations,
                severity_totals["red"],
                severity_totals["yellow"],
                severity_totals["info"],
                total_proposals,
                total_dispatched,
            )

            # --- Phase 3: Send Telegram summary ---
            try:
                gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
                if gateway and gateway.is_running and (violations > 0 or total_dispatched > 0):
                    summary_msg = (
                        f"\U0001f527 Weekly Repair Cycle Complete\n"
                        f"Modules audited: {audited} ({clean} clean, {violations} violations)\n"
                        f"Severity: {severity_totals['red']} red, {severity_totals['yellow']} yellow, {severity_totals['info']} info\n"
                        f"Proposals: {total_proposals} created, {total_dispatched} dispatched"
                    )
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        gateway.send_notification(summary_msg), gateway.loop
                    )
            except Exception as tg_err:
                logger.debug("Repair cycle Telegram summary failed: %s", tg_err)

            self._log_cycle("automated_module_audit", audited, violations, 0)
        except Exception as e:
            self._log_cycle("automated_module_audit", 0, 1, 0, error_message=str(e))
            logger.warning(f"Automated module audit failed: {e}")

    def _daily_code_health_digest(self):
        """Job #51: Send a morning Telegram summary of code health status at 8:00 AM."""
        start = time.time()
        try:
            import asyncio
            from database import get_db_cursor

            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if not gateway or not gateway.is_running:
                logger.debug("Code health digest: Telegram gateway not available, skipping")
                return

            with get_db_cursor() as (conn, cur):
                # Get latest code metrics snapshot
                cur.execute("""
                    SELECT id, total_files, total_lines, scanned_at
                    FROM code_metrics_snapshots
                    ORDER BY scanned_at DESC LIMIT 1
                """)
                snapshot = cur.fetchone()

                # Get audit log summary — green (recent), stale (>30d), unaudited
                cur.execute("""
                    SELECT module_name, status, audited_at
                    FROM code_audit_log
                    WHERE id IN (
                        SELECT MAX(id) FROM code_audit_log GROUP BY module_name
                    )
                """)
                audits = cur.fetchall()

                green = 0
                stale = 0
                violations = 0
                stale_modules = []
                violation_modules = []

                for audit in audits:
                    status = audit.get("status", "")
                    module = audit.get("module_name", "unknown")
                    audited_at = audit.get("audited_at")
                    if status == "violations_found":
                        violations += 1
                        violation_modules.append(module)
                    elif audited_at:
                        from datetime import timedelta
                        age = datetime.now() - audited_at.replace(tzinfo=None) if audited_at.tzinfo else datetime.now() - audited_at
                        if age > timedelta(days=30):
                            stale += 1
                            stale_modules.append(module)
                        else:
                            green += 1
                    else:
                        stale += 1
                        stale_modules.append(module)

                # Get modules changed since last digest (commits in last 24h)
                cur.execute("""
                    SELECT DISTINCT module_name FROM code_audit_log
                    WHERE audited_at > NOW() - INTERVAL '24 hours'
                    ORDER BY module_name
                """)
                changed = [r["module_name"] for r in cur.fetchall()]

                # Count total agent loop jobs
                job_count = len(self.scheduler.get_jobs()) if self.scheduler else 51

                # Build message
                total_files = snapshot["total_files"] if snapshot else 0
                total_lines = snapshot["total_lines"] if snapshot else 0

                lines = [
                    "\U0001f4ca *Daily Code Health Digest*\n",
                    f"\u2705 Green: {green}  \u23f3 Stale: {stale}  \u26a0\ufe0f Violations: {violations}",
                    f"\U0001f4c1 {total_files} files, {total_lines:,} lines",
                ]

                if changed:
                    lines.append(f"\n\U0001f504 Changed (24h): {', '.join(changed[:10])}")
                if violation_modules:
                    lines.append(f"\n\u274c Violations in: {', '.join(violation_modules[:10])}")
                if stale_modules:
                    lines.append(f"\n\u23f0 Stale: {', '.join(stale_modules[:5])}")

                lines.append(f"\n\U0001f916 Job count: {job_count}")

                text = "\n".join(lines)

                # Send to first authorized admin
                cur.execute("""
                    SELECT telegram_id FROM telegram_users
                    WHERE is_authorized = TRUE AND telegram_id IS NOT NULL LIMIT 1
                """)
                tg_user = cur.fetchone()
                if tg_user:
                    loop = gateway._loop
                    asyncio.run_coroutine_threadsafe(
                        gateway._application.bot.send_message(
                            chat_id=tg_user["telegram_id"],
                            text=text, parse_mode="Markdown",
                        ),
                        loop,
                    )
                    logger.info(
                        "Code health digest sent: %d green, %d stale, %d violations",
                        green, stale, violations,
                    )

            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("code_health_digest", 1, 0, duration_ms)

        except Exception as e:
            logger.warning(f"Code health digest failed: {e}")
            self._log_cycle("code_health_digest", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

    def _daily_code_health_scan(self):
        """Job #55: Run codebase scan daily at 2:00 AM. Saves snapshot for Code Health tab."""
        start = time.time()
        try:
            from services.code_metrics_service import scan_codebase, save_snapshot

            logger.info("[CodeHealthScan] Starting daily codebase scan")
            metrics = scan_codebase()
            snapshot_id = save_snapshot(metrics)
            logger.info(
                "[CodeHealthScan] Complete: %d files, %d lines, snapshot #%s",
                metrics.get("total_files", 0),
                metrics.get("total_lines", 0),
                snapshot_id,
            )
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("code_health_scan", 1, 0, duration_ms)

        except Exception as e:
            logger.warning(f"Code health scan failed: {e}")
            self._log_cycle(
                "code_health_scan", 0, 1,
                int((time.time() - start) * 1000),
                error_message=str(e),
            )

    def _competitor_landscape_scan(self):
        """Job #52: Scan AI competitor landscape every 2 weeks, update knowledge_base, notify via Telegram."""
        start = time.time()
        try:
            import asyncio
            from services.competitor_scan_service import run_competitor_scan

            result = run_competitor_scan()
            created = result["created"]
            updated = result["updated"]
            total = result["total"]

            if created == 0 and updated == 0:
                logger.info(f"[Competitors] All {total} competitors up to date, nothing to do")
                self._log_cycle("competitor_scan", 1, 0, int((time.time() - start) * 1000))
                return

            # Build Telegram summary
            lines = [
                "\U0001f50d *AI Competitor Landscape Scan*\n",
                f"\U0001f4ca Tracked: {total} competitors across {len(result.get('summary_lines', []))} changes",
                f"\U0001f195 New: {created}  \U0001f504 Updated: {updated}",
            ]
            if result.get("summary_lines"):
                lines.append("\n*Changes:*")
                lines.extend(result["summary_lines"][:15])

            text = "\n".join(lines)

            # Send Telegram notification
            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if gateway and gateway.is_running:
                from database import get_db_cursor

                with get_db_cursor() as (conn, cur):
                    cur.execute("""
                        SELECT telegram_id FROM telegram_users
                        WHERE is_authorized = TRUE AND telegram_id IS NOT NULL LIMIT 1
                    """)
                    tg_user = cur.fetchone()
                    if tg_user:
                        loop = gateway._loop
                        asyncio.run_coroutine_threadsafe(
                            gateway._application.bot.send_message(
                                chat_id=tg_user["telegram_id"],
                                text=text, parse_mode="Markdown",
                            ),
                            loop,
                        )

            logger.info(
                "[Competitors] Scan complete: %d new, %d updated out of %d tracked",
                created, updated, total,
            )
            self._log_cycle("competitor_scan", 1, 0, int((time.time() - start) * 1000))

        except Exception as e:
            logger.warning(f"[Competitors] Landscape scan failed: {e}")
            self._log_cycle("competitor_scan", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

    def _sync_learned_skills(self):
        """Job #54: Extract skills from ingested GitHub repos and write to Claude rules.

        Scans knowledge_base for github_file entries that contain skill/agent/plugin
        patterns. Builds a summary of learnable skills and writes to
        .claude/rules/learned-skills.md so Claude auto-loads them every session.

        Runs every 6 hours. Only rewrites if new skills are found since last sync.
        """
        start = time.time()
        try:
            from database import get_db_cursor
            import os

            # Write to knowledge_base as vault_note — Claude reads via
            # mcp search_knowledge. Also write to host filesystem if accessible.
            rules_path = "/mnt/archie_brain/.claude/rules/learned-skills.md"

            with get_db_cursor() as (conn, cur):
                # Find skill-related files from ingested repos
                cur.execute("""
                    SELECT DISTINCT
                        SPLIT_PART(title, '/', 1) || '/' || SPLIT_PART(title, '/', 2) as repo,
                        title,
                        LEFT(content, 600) as preview,
                        created_at
                    FROM knowledge_base
                    WHERE knowledge_type = 'github_file'
                    AND content IS NOT NULL AND content != ''
                    AND (
                        title ILIKE '%%/skill%%/README%%'
                        OR title ILIKE '%%/agent%%/README%%'
                        OR title ILIKE '%%/plugin%%/README%%'
                        OR title ILIKE '%%skill-creator%%'
                        OR title ILIKE '%%prompt-engineer%%'
                        OR title ILIKE '%%autonomy%%'
                        OR title ILIKE '%%anti-rationalization%%'
                        OR title ILIKE '%%context-engineering%%'
                        OR title ILIKE '%%writing-skills%%'
                    )
                    ORDER BY created_at DESC
                    LIMIT 100
                """)
                skill_files = cur.fetchall()

                if not skill_files:
                    logger.info("[SkillSync] No skill files found in KB")
                    self._log_cycle("skill_sync", 1, 0, int((time.time() - start) * 1000))
                    return

                # Group by repo
                repos = {}
                for row in skill_files:
                    repo = row["repo"]
                    if repo not in repos:
                        repos[repo] = []
                    repos[repo].append({
                        "title": row["title"],
                        "preview": row["preview"],
                    })

                # Also count total github files per repo for context
                cur.execute("""
                    SELECT
                        SPLIT_PART(title, '/', 1) || '/' || SPLIT_PART(title, '/', 2) as repo,
                        COUNT(*) as total_files
                    FROM knowledge_base
                    WHERE knowledge_type = 'github_file'
                    GROUP BY repo
                    ORDER BY total_files DESC
                """)
                repo_counts = {r["repo"]: r["total_files"] for r in cur.fetchall()}

            # Build the rules file
            lines = [
                "# Learned Skills from GitHub Ingestion",
                "",
                "Auto-generated by Agent Loop Job #54 (every 6 hours).",
                "These skills were extracted from GitHub repos ingested into the knowledge base.",
                f"Last sync: {time.strftime('%Y-%m-%d %H:%M UTC')}",
                "",
                "**To use:** Search `mcp search_knowledge` with the skill name for full content.",
                "",
                "---",
                "",
                "## Ingested Repos",
                "",
                "| Repo | Files | Skill Content |",
                "|------|-------|---------------|",
            ]

            for repo, total in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
                skill_count = len(repos.get(repo, []))
                if skill_count > 0:
                    lines.append(f"| {repo} | {total} | {skill_count} skill files |")
                elif total >= 50:
                    lines.append(f"| {repo} | {total} | general |")

            lines.extend(["", "## Available Skills", ""])

            for repo, skills in sorted(repos.items()):
                lines.append(f"### {repo}")
                lines.append("")
                for skill in skills[:10]:  # Max 10 per repo
                    title = skill["title"].split("/", 2)[-1] if "/" in skill["title"] else skill["title"]
                    # Extract first meaningful line from preview
                    preview_lines = [
                        l.strip() for l in (skill["preview"] or "").split("\n")
                        if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("--")
                    ]
                    desc = preview_lines[0][:120] if preview_lines else "No description"
                    lines.append(f"- **{title}** — {desc}")
                lines.append("")

            lines.extend([
                "---",
                "",
                "## How to Learn from These",
                "",
                "1. `mcp search_knowledge` with the skill name for full content",
                "2. Read the patterns and apply to current task",
                "3. Anti-rationalization patterns (importance 0.95) should be checked when",
                "   about to skip verification or claim something works without testing",
                "",
                "## Key Patterns Already Integrated",
                "",
                "- **Anti-Rationalization** — rationalization table in feedback_03-never-guess.md",
                "- **Skill Creation Workflow** — brainstorm → template → validate → install",
                "- **Prompt Engineering Magic Mode** — auto-refine vague prompts silently",
                "- **Autonomous Execution (Loki Mode)** — auto-resume, kanban monitoring",
            ])

            content = "\n".join(lines) + "\n"
            skill_count = sum(len(s) for s in repos.values())

            # Store in knowledge_base as vault_note (always accessible via MCP)
            with get_db_cursor(commit=True) as (conn2, cur2):
                cur2.execute("""
                    INSERT INTO knowledge_base (
                        knowledge_type, title, content, category,
                        tags, importance_score
                    ) VALUES (
                        'vault_note',
                        'Claude Learned Skills Index (Auto-Generated)',
                        %s, 'agent_skills',
                        %s, 0.90
                    )
                    ON CONFLICT (title) WHERE title IS NOT NULL DO UPDATE SET
                        content = EXCLUDED.content,
                        updated_at = NOW()
                """, (content, ["skill-sync", "auto-generated", "claude-rules"]))

            # Register newly discovered skills in github_skills table
            try:
                with get_db_cursor(commit=True) as (conn3, cur3):
                    new_registered = 0
                    for repo, skills_list in repos.items():
                        for skill_item in skills_list:
                            title = skill_item["title"]
                            # Get KB entry ID for this skill
                            cur3.execute(
                                """SELECT id, file_path FROM knowledge_base
                                   WHERE title = %s AND knowledge_type = 'github_file'
                                   LIMIT 1""",
                                (title,),
                            )
                            kb_row = cur3.fetchone()
                            if not kb_row:
                                continue
                            # Upsert into github_skills
                            skill_name = title.split(": ", 1)[-1] if ": " in title else title
                            cur3.execute(
                                """INSERT INTO github_skills
                                       (kb_entry_id, repo_name, skill_name,
                                        description, file_path, status)
                                   VALUES (%s, %s, %s, %s, %s, 'discovered')
                                   ON CONFLICT (repo_name, file_path) DO NOTHING""",
                                (
                                    kb_row["id"],
                                    repo,
                                    skill_name,
                                    (skill_item.get("preview") or "")[:300],
                                    kb_row["file_path"],
                                ),
                            )
                            if cur3.rowcount > 0:
                                new_registered += 1
                    if new_registered > 0:
                        logger.info(
                            f"[SkillSync] Registered {new_registered} new skills "
                            f"in github_skills table"
                        )
            except Exception as reg_err:
                logger.warning(f"[SkillSync] Skill registration failed: {reg_err}")

            # Try writing to host filesystem (may fail if .claude not mounted)
            try:
                os.makedirs(os.path.dirname(rules_path), exist_ok=True)
                with open(rules_path, "w") as f:
                    f.write(content)
                logger.info(
                    f"[SkillSync] Wrote {len(repos)} repos, "
                    f"{skill_count} skills to {rules_path}"
                )
            except OSError:
                logger.info(
                    f"[SkillSync] {rules_path} not writable from container. "
                    f"Stored {len(repos)} repos, {skill_count} skills in KB only."
                )

            # Telegram notification if new skills discovered
            try:
                prev_count = getattr(self, "_last_skill_count", 0)
                new_skills = skill_count - prev_count if prev_count > 0 else 0
                self._last_skill_count = skill_count

                if new_skills > 0:
                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if bot_token:
                        import requests as _req

                        # Build notification
                        tg_lines = ["🧠 *New Skills Discovered*\n"]
                        tg_lines.append(
                            f"*{new_skills}* new skill files found across "
                            f"*{len(repos)}* repos\n"
                        )
                        tg_lines.append(f"Total skills indexed: *{skill_count}*\n")
                        # Show repos with most skills
                        top_repos = sorted(
                            repos.items(), key=lambda x: len(x[1]), reverse=True
                        )[:5]
                        for rname, rskills in top_repos:
                            tg_lines.append(
                                f"• `{rname}` — {len(rskills)} skills"
                            )
                        tg_lines.append(
                            "\n[View in Consciousness]"
                            "(http://192.168.1.200:3000/tools/consciousness?tab=github)"
                        )
                        text = "\n".join(tg_lines)

                        from db import get_db

                        tg_conn = get_db()
                        tg_cur = tg_conn.cursor()
                        tg_cur.execute(
                            "SELECT telegram_id FROM telegram_users "
                            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                        )
                        for row in tg_cur.fetchall():
                            _req.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={
                                    "chat_id": row[0],
                                    "text": text,
                                    "parse_mode": "Markdown",
                                },
                                timeout=15,
                            )
                        tg_cur.close()
                        tg_conn.close()
                        logger.info(
                            f"[SkillSync] Telegram sent: {new_skills} new skills"
                        )
                elif prev_count == 0:
                    # First run — just store baseline, don't notify
                    self._last_skill_count = skill_count
                    logger.info(
                        f"[SkillSync] Baseline set: {skill_count} skills"
                    )
            except Exception as tg_err:
                logger.warning(f"[SkillSync] Telegram notification failed: {tg_err}")

            self._log_cycle("skill_sync", 1, 0, int((time.time() - start) * 1000))

        except Exception as e:
            logger.warning(f"[SkillSync] Skill sync failed: {e}")
            self._log_cycle("skill_sync", 0, 1, int((time.time() - start) * 1000),
                            error_message=str(e))

    def _github_auto_pull(self):
        """Job #55: Auto-pull tracked GitHub repos and re-index changed files.

        Every 12 hours:
        1. Iterate all repos in github_repositories with a local_path
        2. Git pull each one, detect new commits via rev comparison
        3. For repos with changes, trigger re-index of changed files only
        4. Send Telegram notification summarizing what was refreshed
        """
        import subprocess

        start = time.time()
        pulled = 0
        changed_repos = []
        errors = []

        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, repo_name, repo_type, local_path, status
                       FROM github_repositories
                       WHERE status IN ('cloned', 'indexed')
                       ORDER BY repo_name"""
                )
                repos = cur.fetchall()

            if not repos:
                logger.info("[GitPull] No tracked repos to pull")
                self._log_cycle(
                    "github_auto_pull", 1, 0, int((time.time() - start) * 1000)
                )
                return

            for repo_row in repos:
                repo_name = repo_row["repo_name"]
                local_path = repo_row["local_path"]
                repo_type = repo_row["repo_type"]

                # Skip if not actually cloned on disk
                git_dir = os.path.join(local_path, ".git")
                if not os.path.isdir(git_dir):
                    continue

                try:
                    # Get current rev before pull
                    rev_before = subprocess.run(
                        ["git", "-C", local_path, "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    old_rev = rev_before.stdout.strip() if rev_before.returncode == 0 else None

                    # Pull
                    result = subprocess.run(
                        ["git", "-C", local_path, "pull", "--ff-only"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode != 0:
                        # Try fetch + reset if ff-only fails
                        subprocess.run(
                            ["git", "-C", local_path, "fetch", "origin"],
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                        subprocess.run(
                            ["git", "-C", local_path, "reset", "--hard", "origin/HEAD"],
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )

                    pulled += 1

                    # Get new rev after pull
                    rev_after = subprocess.run(
                        ["git", "-C", local_path, "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    new_rev = rev_after.stdout.strip() if rev_after.returncode == 0 else None

                    # Update last_pull timestamp
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            "UPDATE github_repositories SET last_pull = NOW(), updated_at = NOW() WHERE id = %s",
                            (repo_row["id"],),
                        )

                    # Check if anything changed
                    if old_rev and new_rev and old_rev != new_rev:
                        # Count changed files
                        diff_result = subprocess.run(
                            [
                                "git",
                                "-C",
                                local_path,
                                "diff",
                                "--name-only",
                                old_rev,
                                new_rev,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        changed_files = [
                            f
                            for f in diff_result.stdout.strip().split("\n")
                            if f.strip()
                        ]
                        # Incremental re-index: only changed files, from disk
                        try:
                            from tools.consciousness.github_routes import (
                                _incremental_reindex_from_disk,
                            )

                            owner_part, repo_part = repo_name.split("/", 1)
                            idx_count, del_count, skip_count, idx_errors = (
                                _incremental_reindex_from_disk(
                                    owner_part,
                                    repo_part,
                                    repo_type,
                                    local_path,
                                    changed_files,
                                    importance=0.85,
                                )
                            )
                            logger.info(
                                f"[GitPull] Incremental re-index for {repo_name}: "
                                f"{idx_count} indexed, {del_count} deleted, "
                                f"{skip_count} skipped"
                            )
                        except Exception as idx_err:
                            logger.warning(
                                f"[GitPull] Incremental re-index failed for "
                                f"{repo_name}: {idx_err}"
                            )
                            idx_count = 0

                        changed_repos.append(
                            {
                                "name": repo_name,
                                "type": repo_type,
                                "changed_files": len(changed_files),
                                "indexed": idx_count,
                            }
                        )

                except subprocess.TimeoutExpired:
                    errors.append(f"{repo_name}: timeout")
                except Exception as pull_err:
                    errors.append(f"{repo_name}: {str(pull_err)[:80]}")

            # Send Telegram notification if repos changed
            if changed_repos:
                try:
                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if bot_token:
                        lines = ["🔄 *GitHub Auto-Pull Complete*\n"]
                        total_changed = sum(r["changed_files"] for r in changed_repos)
                        lines.append(
                            f"*{len(changed_repos)}* repos updated, "
                            f"*{total_changed}* files changed\n"
                        )
                        total_indexed = sum(r.get("indexed", 0) for r in changed_repos)
                        for r in changed_repos[:10]:
                            idx = r.get("indexed", 0)
                            lines.append(
                                f"• `{r['name']}` — {r['changed_files']} changed, {idx} re-indexed"
                            )
                        if len(changed_repos) > 10:
                            lines.append(f"• ...and {len(changed_repos) - 10} more")
                        lines.append(
                            f"\n*{total_indexed}* files re-indexed from disk. "
                            f"Skill sync will run next cycle."
                        )
                        text = "\n".join(lines)

                        from db import get_db

                        tg_conn = get_db()
                        tg_cur = tg_conn.cursor()
                        tg_cur.execute(
                            "SELECT telegram_id FROM telegram_users "
                            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                        )
                        for row in tg_cur.fetchall():
                            _req.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={
                                    "chat_id": row[0],
                                    "text": text,
                                    "parse_mode": "Markdown",
                                },
                                timeout=15,
                            )
                        tg_cur.close()
                        tg_conn.close()
                except Exception as tg_err:
                    logger.warning(f"[GitPull] Telegram notification failed: {tg_err}")

            logger.info(
                f"[GitPull] Pulled {pulled} repos, "
                f"{len(changed_repos)} had changes, {len(errors)} errors"
            )
            self._log_cycle(
                "github_auto_pull",
                1,
                0,
                int((time.time() - start) * 1000),
            )

        except Exception as e:
            logger.warning(f"[GitPull] Auto-pull failed: {e}")
            self._log_cycle(
                "github_auto_pull",
                0,
                1,
                int((time.time() - start) * 1000),
                error_message=str(e),
            )

    def _analyze_discovered_skills(self):
        """Job #56: AI-analyze discovered skills from GitHub repos.

        Picks up skills with status='discovered' from github_skills table,
        sends each to Bridge for analysis (quality, capabilities, use cases),
        updates the skill record with results.

        Processes up to 10 skills per run to avoid overloading the Bridge.
        Runs every 6 hours, offset from skill sync.
        """
        # Recovery: reset skills stuck in 'analyzing' for >1 hour (crash orphans)
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE github_skills SET status = 'discovered', updated_at = NOW()
                WHERE status = 'analyzing' AND updated_at < NOW() - INTERVAL '1 hour'
            """)
            recovered = cur.rowcount
            conn.commit()
            cur.close()
            conn.close()
            if recovered:
                logger.info("[SkillAnalyzer] Recovered %d stuck 'analyzing' skills", recovered)
        except Exception as e:
            logger.warning("[SkillAnalyzer] Recovery query failed: %s", e)

        start = time.time()
        analyzed = 0
        errors_count = 0

        try:
            from database import get_db_cursor
            from bridge_dispatcher import dispatch_json

            # Fetch up to 10 unanalyzed skills
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT gs.id, gs.repo_name, gs.skill_name, gs.file_path,
                              gs.description, kb.content
                       FROM github_skills gs
                       LEFT JOIN knowledge_base kb ON kb.id = gs.kb_entry_id
                       WHERE gs.status = 'discovered'
                       ORDER BY gs.created_at ASC
                       LIMIT 10"""
                )
                skills = cur.fetchall()

            if not skills:
                logger.info("[SkillAnalyzer] No discovered skills to analyze")
                self._log_cycle(
                    "skill_analyzer", 1, 0, int((time.time() - start) * 1000)
                )
                return

            logger.info(f"[SkillAnalyzer] Analyzing {len(skills)} skills")

            for skill in skills:
                skill_id = skill["id"]
                content = skill.get("content") or skill.get("description") or ""
                if not content or len(content.strip()) < 20:
                    # Too little content to analyze — mark as analyzed with low score
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE github_skills
                               SET status = 'analyzed', quality_score = 1,
                                   analysis = %s, updated_at = NOW()
                               WHERE id = %s""",
                            (
                                json.dumps({"note": "Insufficient content for analysis"}),
                                skill_id,
                            ),
                        )
                    analyzed += 1
                    continue

                # Mark as analyzing
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        "UPDATE github_skills SET status = 'analyzing', updated_at = NOW() WHERE id = %s",
                        (skill_id,),
                    )

                # Build analysis prompt
                truncated = content[:3000]
                prompt = f"""Analyze this skill/tool from the GitHub repository "{skill['repo_name']}".
File: {skill['skill_name']}

Content:
---
{truncated}
---

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "quality_score": <1-5 integer, 5=production-ready, 4=good, 3=decent, 2=basic, 1=stub>,
  "summary": "<1-2 sentence description of what this skill does>",
  "capabilities": [<list of capability tags like "code-review", "testing", "debugging", "deployment", "documentation", "refactoring", "security", "monitoring", "data-processing", "ai-prompting", "automation">],
  "target_departments": [<which A.R.C.H.I.E. departments could use this: "Engineering & Technology", "Research & Development", "Analytics & Intelligence", "Creative & Design", "Security & Compliance", "Operations & Infrastructure", "Marketing & Communications", "Logistics & Supply Chain", "Executive Office", "Diplomatic & External Relations", "Finance & Accounting", "Customer Success & Support", "Human Resources & Culture", "Medical & Wellness", "Legal & Regulatory", "Documentation & Knowledge">],
  "adaptation_value": "<high/medium/low - how valuable would it be to adapt this for A.R.C.H.I.E.>",
  "adaptation_notes": "<what would need to change to make it A.R.C.H.I.E.-native>"
}}"""

                system_prompt = (
                    "You are a skill analyst for the A.R.C.H.I.E. platform. "
                    "Evaluate external skills for quality, capabilities, and "
                    "potential adaptation into A.R.C.H.I.E.'s agent workforce. "
                    "Respond with valid JSON only."
                )

                try:
                    result = dispatch_json(
                        capability="code_analysis",
                        prompt=prompt,
                        module_id="skill_analyzer",
                        system_prompt=system_prompt,
                    )

                    if result and isinstance(result, dict):
                        quality = min(5, max(1, int(result.get("quality_score", 2))))
                        capabilities = result.get("capabilities", [])
                        summary = result.get("summary", "")
                        target_departments = result.get("target_departments", result.get("target_stations", []))

                        # Determine final status based on quality
                        new_status = "registered" if quality >= 3 else "analyzed"

                        with get_db_cursor(commit=True) as (conn2, cur2):
                            cur2.execute(
                                """UPDATE github_skills
                                   SET status = %s,
                                       quality_score = %s,
                                       description = %s,
                                       capabilities = %s,
                                       analysis = %s,
                                       updated_at = NOW()
                                   WHERE id = %s""",
                                (
                                    new_status,
                                    quality,
                                    summary[:500] if summary else skill.get("description"),
                                    json.dumps(capabilities),
                                    json.dumps(result),
                                    skill_id,
                                ),
                            )

                            # Auto-assign to agents if quality >= 3
                            if quality >= 3 and target_departments:
                                # Map department names to skill_category values
                                department_to_category = {
                                    "Engineering & Technology": "engineering",
                                    "Research & Development": "research",
                                    "Analytics & Intelligence": "analytics",
                                    "Creative & Design": "creative",
                                    "Security & Compliance": "security",
                                    "Operations & Infrastructure": "operations",
                                    "Marketing & Communications": "communications",
                                    "Logistics & Supply Chain": "logistics",
                                    "Executive Office": "operations",
                                    "Diplomatic & External Relations": "diplomacy",
                                    "Finance & Accounting": "finance",
                                    "Customer Success & Support": "support",
                                    "Human Resources & Culture": "hr",
                                    "Medical & Wellness": "medical",
                                    "Legal & Regulatory": "legal",
                                    "Documentation & Knowledge": "documentation",
                                    # Legacy station names (backward compat)
                                    "ENGINEERING": "engineering",
                                    "RESEARCH": "research",
                                    "ANALYTICS": "analytics",
                                    "CREATIVE": "creative",
                                    "SECURITY": "security",
                                    "OPERATIONS": "operations",
                                    "COMMUNICATIONS": "communications",
                                    "LOGISTICS": "logistics",
                                    "COMMAND": "operations",
                                    "DIPLOMATIC": "diplomacy",
                                }
                                categories = [
                                    department_to_category.get(s, s.lower())
                                    for s in target_departments
                                ]

                                # Find agents in target departments
                                cur2.execute(
                                    """SELECT DISTINCT a.id, a.name
                                       FROM agents a
                                       WHERE a.department IS NOT NULL
                                         AND a.shift_state IN ('active', 'deployed')
                                         AND EXISTS (
                                             SELECT 1 FROM agent_skills ask
                                             WHERE ask.agent_id = a.id
                                               AND ask.skill_category = ANY(%s)
                                         )""",
                                    (categories,),
                                )
                                target_agents = cur2.fetchall()

                                assigned_ids = []
                                for agent_row in target_agents:
                                    # Use first capability as skill name
                                    gh_skill_name = (
                                        f"gh:{capabilities[0]}"
                                        if capabilities
                                        else f"gh:{skill['skill_name'][:50]}"
                                    )
                                    add_skill(
                                        agent_row["id"],
                                        gh_skill_name,
                                        level=min(quality, 3),
                                        category=categories[0] if categories else "general",
                                    )
                                    assigned_ids.append(agent_row["id"])

                                # Update github_skills with assigned agent IDs
                                if assigned_ids:
                                    cur2.execute(
                                        """UPDATE github_skills
                                           SET agent_ids = %s
                                           WHERE id = %s""",
                                        (json.dumps(assigned_ids), skill_id),
                                    )
                                    logger.info(
                                        f"[SkillAnalyzer] Assigned skill to "
                                        f"{len(assigned_ids)} agents: "
                                        f"{[a['name'] for a in target_agents[:3]]}"
                                    )

                        analyzed += 1
                        logger.info(
                            f"[SkillAnalyzer] Analyzed {skill['skill_name']} "
                            f"from {skill['repo_name']}: quality={quality}, "
                            f"caps={capabilities[:3]}"
                        )
                    else:
                        # Bridge returned nothing — reset to discovered for retry
                        with get_db_cursor(commit=True) as (conn2, cur2):
                            cur2.execute(
                                """UPDATE github_skills
                                   SET status = 'discovered', updated_at = NOW()
                                   WHERE id = %s""",
                                (skill_id,),
                            )
                        errors_count += 1

                except Exception as dispatch_err:
                    logger.warning(
                        f"[SkillAnalyzer] Dispatch failed for skill #{skill_id}: "
                        f"{str(dispatch_err)[:80]}"
                    )
                    # Reset to discovered for retry
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE github_skills
                               SET status = 'discovered', updated_at = NOW()
                               WHERE id = %s""",
                            (skill_id,),
                        )
                    errors_count += 1

            # Send Telegram summary if skills were analyzed
            if analyzed > 0:
                try:
                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if bot_token:
                        import requests as _req

                        text = (
                            f"🔬 *Skill Analysis Complete*\n\n"
                            f"*{analyzed}* skills analyzed, *{errors_count}* errors\n"
                            f"_{len(skills)} skills processed this cycle_\n\n"
                            f"[View Skills](http://192.168.1.200:3000/tools/consciousness?tab=github)"
                        )

                        from db import get_db

                        tg_conn = get_db()
                        tg_cur = tg_conn.cursor()
                        tg_cur.execute(
                            "SELECT telegram_id FROM telegram_users "
                            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                        )
                        for row in tg_cur.fetchall():
                            _req.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={
                                    "chat_id": row[0],
                                    "text": text,
                                    "parse_mode": "Markdown",
                                },
                                timeout=15,
                            )
                        tg_cur.close()
                        tg_conn.close()
                except Exception as tg_err:
                    logger.warning(
                        f"[SkillAnalyzer] Telegram notification failed: {tg_err}"
                    )

            logger.info(
                f"[SkillAnalyzer] Done: {analyzed} analyzed, {errors_count} errors"
            )
            self._log_cycle(
                "skill_analyzer", 1, 0, int((time.time() - start) * 1000)
            )

        except Exception as e:
            logger.warning(f"[SkillAnalyzer] Job failed: {e}")
            self._log_cycle(
                "skill_analyzer",
                0,
                1,
                int((time.time() - start) * 1000),
                error_message=str(e),
            )

    def _check_fleet_health(self):
        """Job #45: Monitor fleet node heartbeats — return agents to barracks if offline."""
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            dispatcher.check_fleet_health()
        except Exception as e:
            logger.warning(f"Fleet health check failed: {e}")

    def _check_mesh_health(self):
        """Job #53: Monitor mesh VPN connectivity for all fleet nodes.

        Pings each node's mesh_ip, updates mesh_status/mesh_latency_ms
        in remote_nodes, and logs to mesh_health_log. Triggers fleet cache
        refresh on status transitions (disconnected→connected or vice versa).
        """
        try:
            import socket
            import time as _time
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, node_name, mesh_ip, mesh_status
                       FROM remote_nodes
                       WHERE mesh_ip IS NOT NULL
                         AND is_active = true
                         AND approval_status = 'approved'"""
                )
                nodes = cur.fetchall()

            if not nodes:
                return

            changed = False
            for node in nodes:
                mesh_ip = node["mesh_ip"]
                old_status = node["mesh_status"]
                node_id = node["id"]

                # TCP connect to Ollama port on mesh IP (fast reachability check)
                latency_ms = None
                new_status = "disconnected"
                conn_type = None
                try:
                    start = _time.monotonic()
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3)
                    s.connect((mesh_ip, 11434))
                    s.close()
                    elapsed = (_time.monotonic() - start) * 1000
                    latency_ms = int(elapsed)
                    new_status = "connected"
                    conn_type = "direct"
                except Exception:
                    new_status = "disconnected"

                # Update remote_nodes
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """UPDATE remote_nodes
                           SET mesh_status = %s,
                               mesh_latency_ms = %s,
                               mesh_connection_type = %s,
                               mesh_last_seen = CASE WHEN %s = 'connected' THEN NOW() ELSE mesh_last_seen END
                           WHERE id = %s""",
                        (new_status, latency_ms, conn_type, new_status, node_id),
                    )

                    # Log to mesh_health_log
                    cur.execute(
                        """INSERT INTO mesh_health_log
                           (node_id, mesh_ip, latency_ms, connection_type, is_reachable)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (
                            node_id,
                            mesh_ip,
                            latency_ms,
                            conn_type,
                            new_status == "connected",
                        ),
                    )
                    conn.commit()

                # Detect status transitions
                if old_status != new_status:
                    changed = True
                    logger.info(
                        f"[MeshHealth] Node {node['node_name']} mesh "
                        f"{old_status}→{new_status} ({mesh_ip})"
                    )

            # Refresh fleet cache if any node changed status
            if changed:
                try:
                    from ai_bridge.bridge_dispatcher import get_dispatcher

                    dispatcher = get_dispatcher()
                    dispatcher._refresh_fleet_cache()
                except Exception:
                    pass

            # Prune old health log entries (keep 7 days)
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "DELETE FROM mesh_health_log WHERE checked_at < NOW() - INTERVAL '7 days'"
                    )
                    conn.commit()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Mesh health check failed: {e}")

    def _save_model_state(self):
        """Job #46: Save current loaded models to DB for restart recovery."""
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            dispatcher._save_model_state()  # Hub
            # Also save state for each online node
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id FROM remote_nodes
                       WHERE is_active = true AND deployment_mode != 'starbase'
                       AND last_heartbeat > NOW() - INTERVAL '2 minutes'"""
                )
                for row in cur.fetchall():
                    try:
                        dispatcher._save_model_state(node_db_id=row["id"])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Model state save failed: {e}")

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
            from ai_bridge.bridge_dispatcher import get_dispatcher

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
        """Job #49: Trigger consciousness analysis batch every 6 hours.

        Only runs if the analysis server loop is enabled in system_config.
        Uses _trigger_loop_op() from processing_routes which handles
        item selection, job creation, and background threading.
        """
        try:
            from tools.consciousness.processing_routes import (
                get_server_loops,
                _trigger_loop_op,
            )

            loops = get_server_loops()
            if not loops.get("analysis"):
                logger.debug(
                    "[Consciousness Batch] Analysis loop disabled — skipping"
                )
                return

            logger.info(
                "[Consciousness Batch] Triggering scheduled analysis batch"
            )
            _trigger_loop_op("analysis")
        except Exception as e:
            logger.warning(f"[Consciousness Batch] Analysis batch failed: {e}")

    def _consciousness_embedding_batch(self):
        """Job #50: Trigger consciousness embedding batch every 4 hours.

        Only runs if the embedding server loop is enabled in system_config.
        Uses _trigger_loop_op() from processing_routes which handles
        item selection, job creation, and background threading.
        """
        try:
            from tools.consciousness.processing_routes import (
                get_server_loops,
                _trigger_loop_op,
            )

            loops = get_server_loops()
            if not loops.get("embedding"):
                logger.debug(
                    "[Consciousness Batch] Embedding loop disabled — skipping"
                )
                return

            logger.info(
                "[Consciousness Batch] Triggering scheduled embedding batch"
            )
            _trigger_loop_op("embedding")
            self._log_cycle("consciousness_embedding", 1, 0, 0)
        except Exception as e:
            self._log_cycle("consciousness_embedding", 0, 1, 0, error_message=str(e))
            logger.warning(f"[Consciousness Batch] Embedding batch failed: {e}")

    # ── Job #59 — Standalone Health Monitor ─────────────────────────────

    _standalone_last_status = {}

    def _check_standalone_health(self):
        """Job #59: Monitor standalone product health, alert on downtime."""
        import os
        import requests as req
        from database import get_db_cursor

        standalones = [
            {
                "name": "Kytran System Operations",
                "url": os.getenv("STANDALONE_SYSOPS_URL", "http://192.168.1.200:8085"),
                "health_path": "/dashboard/api/health",
            },
        ]

        for product in standalones:
            key = product["name"]
            url = f"{product['url']}{product['health_path']}"
            was_down = self._standalone_last_status.get(key) == "down"

            try:
                resp = req.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "unknown")
                    if status in ("healthy", "operational"):
                        if was_down:
                            # Nagios handles monitoring alerts — log only
                            logger.info(f"[Standalone Health] {key} recovered")
                        self._standalone_last_status[key] = "up"
                        continue

                # Non-200 or unhealthy status
                raise Exception(f"HTTP {resp.status_code}")

            except Exception as e:
                if not was_down:
                    # Nagios handles monitoring alerts — log only
                    logger.error(f"[Standalone Health] {key} is DOWN: {e}")
                self._standalone_last_status[key] = "down"

    def _department_metrics_rollup(self):
        """Job #60: Department metrics rollup — daily at 2:00 AM.
        Owned by Analytics & Intelligence (S.P.E.C.T.R.A.)."""
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from services.work_tracking_service import compute_department_metrics

            result = compute_department_metrics(period_hours=24)
            logger.info(
                "Department metrics rollup: %d departments computed",
                result.get("departments_computed", 0),
            )
            self._log_cycle(
                "department_metrics_rollup",
                result.get("departments_computed", 0),
                0,
                0,
            )
        except Exception as e:
            self._log_cycle(
                "department_metrics_rollup", 0, 1, 0, error_message=str(e)
            )
            logger.warning("Department metrics rollup failed: %s", e)

    def _renew_fleet_ssl(self):
        """Job #61: Renew wildcard SSL cert if expiring within 30 days.
        Owned by Security & Compliance (V.I.G.I.L.)."""
        try:
            from ai_bridge.cert_manager import check_cert_expiry, renew_wildcard_cert

            cert_dir = "/opt/archie-fleet/certs/wildcard"
            cert_path = os.path.join(cert_dir, "fullchain.pem")
            days_left = check_cert_expiry(cert_path)

            if days_left > 30:
                logger.info(f"[SSL] Wildcard cert valid for {days_left} more days, skipping renewal")
                return

            if days_left == -1:
                logger.info("[SSL] No wildcard cert found, attempting first issuance...")
            else:
                logger.info(f"[SSL] Cert expires in {days_left} days, starting renewal...")

            success, message = renew_wildcard_cert("kytranempowerment.com", cert_dir)

            if success:
                logger.info(f"[SSL] Renewal successful: {message}")
            else:
                logger.error(f"[SSL] Renewal failed: {message}")
                from database import get_db_cursor

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO system_notifications
                           (type, title, message, source, priority, visibility, is_read, created_at)
                           VALUES ('error', 'SSL Renewal Failed', %s, 'agent_loop', 'high', 'admin', FALSE, NOW())""",
                        (message,),
                    )
        except Exception as e:
            logger.error(f"[SSL] Fleet SSL renewal error: {e}")


    # ── Job #62 — Social Video: Generate Content ──────────────────────────

    def _social_video_generate_content(self):
        """Job #62: Generate social video content from templates every 4 hours."""
        import random
        try:
            from platform_v2.tools.media_studio.services import social_video_service as svs

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
            from platform_v2.tools.media_studio.services.social_video_worker import process_queue
            process_queue()

        except Exception as e:
            logger.error("[SocialVideo] Content generation job failed: %s", e)

    # ── Job #63 — Social Video: Auto-Approve ──────────────────────────────

    def _social_video_auto_approve(self):
        """Job #63: Auto-approve eligible social video queue items every 15 minutes."""
        try:
            from platform_v2.tools.media_studio.services import social_video_service as svs

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
            from platform_v2.tools.media_studio.services import social_video_service as svs

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
                                from platform_v2.tools.social_media.publishing_service import publish_video
                                result = publish_video(platform, video_path, caption, hashtags)
                                if result:
                                    post_urls[platform] = result
                            elif platform == "indeed":
                                from platform_v2.tools.social_media.platform_clients import get_indeed_client
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

    # Dispatch summarization
    from bridge_dispatcher import get_dispatcher
    dispatcher = get_dispatcher()

    # Summary
    summary_result = dispatcher.dispatch(
        prompt=f"Summarize this conversation in 2-3 sentences:\n\n{conv_text}",
        system_prompt="You are a helpful assistant. Provide a concise summary.",
        agent_name=agent.get('name'),
    )
    summary = summary_result.get('response', '').strip()

    if summary:
        cur.execute("""
            INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
            VALUES (%s, %s, 'summary', %s)
        """, (convo['agent_id'], convo['user_id'], summary))

    # Pinned memories
    pinned_result = dispatcher.dispatch(
        prompt=f"What important facts should you remember about this user from this conversation? List each fact on its own line. Only include facts worth remembering for future conversations.\n\n{conv_text}",
        system_prompt="You are a helpful assistant. Extract key facts about the user.",
        agent_name=agent.get('name'),
    )
    pinned_text = pinned_result.get('response', '').strip()

    if pinned_text:
        for line in pinned_text.split('\n'):
            line = line.strip().lstrip('•-* ')
            if line and len(line) > 10:
                cur.execute("""
                    INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
                    VALUES (%s, %s, 'pinned', %s)
                """, (convo['agent_id'], convo['user_id'], line))

    conn.commit()
