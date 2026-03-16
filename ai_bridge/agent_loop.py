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

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("agent_loop")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


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
            station = action_data.get("station_code", "?")
            lines.append(f"Type: Create New Agent")
            lines.append(f"Capability: {cap}")
            lines.append(f"Station: {station}")
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
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if tier-1 auto-approve
        cur.execute(
            "SELECT config_value FROM autonomy_config WHERE config_key = 'tier1_auto_approve'"
        )
        row = cur.fetchone()
        tier1_types = row["config_value"].get("types", []) if row else []

        effective_tier = 1 if action_type in tier1_types else tier

        # Dedup: skip if there's already a pending approval of the same type
        if effective_tier > 1:
            cur.execute(
                "SELECT id FROM autonomy_approval_queue WHERE action_type = %s AND status = 'pending' LIMIT 1",
                (action_type,),
            )
            if cur.fetchone():
                logger.info(f"Skipping duplicate {action_type} — pending approval already exists")
                cur.close()
                conn.close()
                return None

        status = "approved" if effective_tier == 1 else "pending"
        approved_at = "NOW()" if effective_tier == 1 else "NULL"

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
        approval_id = cur.fetchone()["id"]
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

        self._running = True
        logger.info("Agent loop started with 31 jobs")

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

            # Get SMTP settings
            cur.execute(
                "SELECT * FROM email_settings WHERE is_default = true AND is_active = true"
            )
            smtp_settings = cur.fetchone()

            if not smtp_settings:
                logger.warning(
                    "Agent loop: No active SMTP settings, skipping email queue"
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

                    # Send via SMTP
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
            from email_intelligence import EmailIntelligence

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
            from email_intelligence import EmailIntelligence

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

                # Trigger Phase 4 auto-execution in background thread
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
        """Run IAAE ethics monitoring cycle (every 15 min)."""
        start = time.time()
        try:
            from ai_bridge.ethics_monitor import EthicsMonitor
            monitor = EthicsMonitor()
            result = monitor.run_full_monitoring_cycle()
            duration_ms = int((time.time() - start) * 1000)
            checked = getattr(result, 'agents_checked', 0)
            issues = getattr(result, 'issues_found', 0)
            alerts = getattr(result, 'alerts_created', 0)
            if checked > 0 or issues > 0 or alerts > 0:
                logger.info(f"Ethics monitoring: {checked} checked, "
                           f"{issues} issues, {alerts} alerts")
                self._log_cycle("ethics_monitoring", checked, issues, duration_ms,
                               details={"issues": issues, "alerts": alerts})
        except Exception as e:
            logger.error(f"Ethics monitoring failed: {e}")
            duration_ms = int((time.time() - start) * 1000)
            self._log_cycle("ethics_monitoring", 0, 1, duration_ms, error_message=str(e))

    def _reap_stale_jobs(self):
        """Reap orphaned bridge jobs that stopped updating (every 2 min)."""
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            reaped = dispatcher.reap_stale_jobs(max_age_minutes=5)
            if reaped:
                logger.info(f"Stale job reaper: cleaned {reaped} orphaned jobs")
        except Exception as e:
            logger.debug(f"Stale job reaper failed: {e}")

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
            logger.debug(f"Notification archiver failed: {e}")

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
            logger.debug(f"Network discovery failed: {e}")

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

                cur.execute("""
                    UPDATE agent_emotional_state
                    SET stress_level = %s, energy_level = %s, current_mood = %s,
                        timestamp = NOW()
                    WHERE agent_id = %s
                """, (round(stress, 2), round(energy, 2), mood, row["agent_id"]))

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
        Scan for idle agents and volunteer them at stations with pending work.
        Runs every 5 minutes.
        - Find stations with recent task failures
        - Find idle agents not at those stations
        - Create notifications for volunteering events
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            start = time.time()

            # Find stations with recent failures and no idle primaries
            cur.execute("""
                SELECT tel.station_code, bs.id AS station_id,
                       COUNT(*) AS recent_failures
                FROM task_execution_log tel
                JOIN bridge_stations bs ON tel.station_code = bs.station_code
                WHERE tel.success = FALSE
                  AND tel.created_at > NOW() - INTERVAL '30 minutes'
                  AND bs.is_active = TRUE
                GROUP BY tel.station_code, bs.id
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
                SELECT a.id, a.name, a.model, sa.station_id,
                       bs.station_code AS home_station
                FROM agents a
                JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
                JOIN bridge_stations bs ON sa.station_id = bs.id
                LEFT JOIN bridge_jobs bj ON bj.agent_name = a.name AND bj.status = 'running'
                LEFT JOIN agent_rest_cycles arc ON a.id = arc.agent_id AND arc.ended_at IS NULL
                WHERE a.status = 'active'
                  AND bj.id IS NULL
                  AND arc.id IS NULL
                  AND a.shift_state IN ('active', 'winding_down')
            """)
            idle_agents = cur.fetchall()

            if not idle_agents:
                cur.close()
                conn.close()
                return

            volunteered = 0
            for job in pending_jobs:
                # Find an idle agent NOT from this station
                volunteer = None
                for agent in idle_agents:
                    if agent["home_station"] != job["station_code"]:
                        volunteer = agent
                        break

                if volunteer:
                    logger.info(
                        f"Volunteering {volunteer['name']} from {volunteer['home_station']} "
                        f"to help {job['station_code']} ({job['recent_failures']} recent failures)"
                    )
                    self._create_notification(
                        f"Fleet: {volunteer['name']} volunteering at {job['station_code']}",
                        "info",
                        {"agent": volunteer["name"], "station": job["station_code"]},
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
                    logger.debug(f"Failed to generate failure analysis for {agent_name}/{capability}: {e}")

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
                cur.execute("""
                    UPDATE agent_skills
                    SET proficiency_level = %s, updated_at = NOW()
                    WHERE agent_id = %s AND skill_name = %s
                      AND proficiency_level < %s
                """, (target_level, agent_id, skill_name, target_level))

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
                cur.execute("""
                    UPDATE agent_emotional_state
                    SET energy_level = LEAST(1.0, energy_level + 0.1),
                        stress_level = GREATEST(0.0, stress_level - 0.1),
                        current_mood = 'accomplished',
                        timestamp = NOW()
                    WHERE agent_id = %s
                """, (agent_id,))

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
                    logger.debug(f"Training tick Telegram notification failed: {e}")

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
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO autonomy_loop_log
                (job_name, status, items_processed, items_failed, duration_ms, details, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job_name,
                    status,
                    items_processed,
                    items_failed,
                    duration_ms,
                    json.dumps(details or {}),
                    error_message,
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
