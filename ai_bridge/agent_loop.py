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


def log_governance_event(event_type, action, outcome, details=None):
    """Log a governance event to the immutable audit log"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, action, outcome, details, timestamp)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (event_type, action, outcome, json.dumps(details or {})),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log governance event: {e}")


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

        self._running = True
        logger.info("Agent loop started with 12 jobs")

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
            "agent_browser_tasks",
            "agent_briefings",
            "agent_anomaly_detection",
            "agent_reports",
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
                  AND scheduled_for <= NOW()
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

                # Create notification for new emails
                if fetched > 0:
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    self._create_notification(
                        cur,
                        notification_type="info",
                        title="New Emails",
                        message=f"{fetched} new email(s) received and {analyzed} analyzed",
                        source="email_intelligence",
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

            if analyzed > 0:
                log_governance_event(
                    "email_auto_analyze",
                    "execute",
                    "success",
                    {"analyzed": analyzed, "remaining": len(rows) - analyzed},
                )
                logger.info(f"Auto-analyzed {analyzed} emails")
        except Exception as e:
            logger.error(f"Auto-analyze job failed: {e}")
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
        try:
            gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
            if gateway and gateway.is_running:
                gateway.forward_notifications()
        except Exception as e:
            logger.error(f"Telegram notification forwarding error: {e}")

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
        gateway = self.flask_app.config.get("TELEGRAM_GATEWAY")
        if not gateway or not gateway.is_running:
            return
        cur = None
        conn = None
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

        else:
            logger.warning(f"Unknown approved action type: {action_type}")
            return {"skipped": True, "reason": f"Unknown action type: {action_type}"}

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
    ):
        """Create a system notification with deduplication."""
        # Deduplication: check for same message in last 5 minutes
        cur.execute(
            """
            SELECT id, grouped_count FROM system_notifications
            WHERE message = %s AND type = %s AND source = %s
              AND created_at > NOW() - INTERVAL '5 minutes'
              AND is_read = FALSE
            ORDER BY created_at DESC LIMIT 1
            """,
            (message, notification_type, source),
        )
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
                (type, title, message, source, priority, source_icon, related_action, is_read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, NOW())
                """,
                (
                    notification_type,
                    title,
                    message,
                    source,
                    priority,
                    "bot",
                    related_action,
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
