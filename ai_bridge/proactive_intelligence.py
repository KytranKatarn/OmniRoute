"""
Proactive Intelligence — Briefings, Anomaly Detection, Report Generation

- BriefingGenerator: Compose morning/evening briefings from multiple data sources
- AnomalyDetector: SQL-based threshold checking, rate spikes, absence detection
- ReportEngine: Scheduled report generation with AI formatting

No GPU model swaps — uses dolphin3 (always-loaded) for natural language formatting.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
from datetime import datetime
from services.time_utils import now_local_str
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from db import get_db

logger = logging.getLogger("proactive_intelligence")


# ============================================================================
# BRIEFING GENERATOR
# ============================================================================


class BriefingGenerator:
    """Compose daily briefings from multiple data sources."""

    def generate_briefing(self, briefing_id: int) -> Optional[int]:
        """
        Generate a briefing from its configuration.

        Returns briefing_history ID, or None on failure.
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM briefings WHERE id = %s AND is_active = TRUE", (briefing_id,))
        briefing = cur.fetchone()
        if not briefing:
            cur.close()
            conn.close()
            return None

        sections = briefing.get("sections", [])
        sections_data = {}

        # Gather data for each section. Each section runs inside its own
        # SAVEPOINT so a single failing query (e.g. schema drift) rolls back
        # ONLY that section — without a savepoint the failure aborts the whole
        # transaction and every later section PLUS the briefing_history INSERT
        # below cascade-fail with "current transaction is aborted", masking the
        # real per-section error (observed 2026-05-30 20:04).
        for section in sections:
            try:
                cur.execute("SAVEPOINT briefing_section")
                sections_data[section] = self._gather_section(cur, section)
                cur.execute("RELEASE SAVEPOINT briefing_section")
            except Exception as e:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT briefing_section")
                except Exception:
                    conn.rollback()
                logger.warning(f"Failed to gather section '{section}': {e}")
                sections_data[section] = {"error": str(e)}

        # Compose briefing with AI
        content = self._compose_briefing(briefing, sections_data)

        # Generate short summary for Telegram
        summary = content[:500] if len(content) <= 500 else content[:497] + "..."

        # Store
        cur.execute(
            """
            INSERT INTO briefing_history (briefing_id, content, summary, sections_data)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (briefing_id, content, summary, json.dumps(sections_data, default=str)),
        )
        history_id = cur.fetchone()["id"]
        conn.commit()

        # Deliver
        delivery_status = self._deliver_briefing(cur, conn, briefing, content, summary)

        cur.execute(
            "UPDATE briefing_history SET delivery_status = %s WHERE id = %s",
            (json.dumps(delivery_status), history_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        return history_id

    def _gather_section(self, cur, section: str) -> dict:
        """Gather data for a briefing section."""
        if section == "notifications":
            cur.execute(
                """
                SELECT type, title, message, priority, created_at
                FROM system_notifications
                WHERE is_read = FALSE AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 10
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        elif section == "emails":
            cur.execute(
                """
                SELECT from_name, from_address, subject, ai_category, ai_priority, ai_summary, received_at
                FROM email_inbox
                WHERE is_read = FALSE AND is_archived = FALSE
                ORDER BY ai_priority ASC NULLS LAST, received_at DESC
                LIMIT 10
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        elif section == "tasks":
            cur.execute(
                """
                SELECT name, status, priority, due_date
                FROM scheduled_tasks
                WHERE status IN ('pending', 'overdue')
                ORDER BY priority ASC, due_date ASC NULLS LAST
                LIMIT 10
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        elif section == "anomalies":
            cur.execute(
                """
                SELECT ad.title, ad.severity, ad.description, ad.current_value,
                       ad.threshold_value, ad.created_at, ar.name as rule_name
                FROM anomaly_detections ad
                JOIN anomaly_rules ar ON ad.rule_id = ar.id
                WHERE ad.acknowledged = FALSE AND ad.created_at > NOW() - INTERVAL '24 hours'
                ORDER BY
                    CASE ad.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                    ad.created_at DESC
                LIMIT 5
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        elif section == "calendar":
            # Placeholder — would integrate with Google Calendar if configured
            return {"items": [], "note": "Calendar integration not yet configured"}

        elif section == "approvals":
            cur.execute(
                """
                SELECT action_type, reason, priority, created_at
                FROM autonomy_approval_queue
                WHERE status = 'pending'
                ORDER BY priority ASC LIMIT 5
                """
            )
            return {"items": [dict(r) for r in cur.fetchall()]}

        return {}

    def _compose_briefing(self, briefing: dict, sections_data: dict) -> str:
        """Compose a natural language briefing using AI."""
        briefing_type = briefing.get("briefing_type", "daily")
        now = now_local_str("%A, %B %d, %Y at %I:%M %p %Z")

        # Build raw data summary
        raw_parts = [f"{briefing_type.title()} Briefing — {now}\n"]

        for section, data in sections_data.items():
            items = data.get("items", [])
            if not items:
                raw_parts.append(f"\n{section.upper()}: Nothing new.")
                continue

            raw_parts.append(f"\n{section.upper()}: {len(items)} item(s)")
            for item in items[:5]:
                raw_parts.append(f"  - {json.dumps(item, default=str)[:200]}")

        raw_summary = "\n".join(raw_parts)

        # Use AI to format
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            prompt = f"""Format this raw data into a clean, conversational briefing.
Be concise. Use bullet points. Highlight anything urgent.
No markdown, plain text only (for Telegram compatibility).

{raw_summary}

Write the briefing:"""

            dispatcher = get_dispatcher()
            result = dispatcher.request_work("chat", prompt, "proactive_intelligence", timeout=120)
            content = result.response.strip() if result.success else None
            if not content:
                content = raw_summary
                logger.warning("Briefing AI formatting failed, using raw summary")
            return content

        except Exception as e:
            logger.warning(f"AI formatting failed, using raw: {e}")
            return raw_summary

    def _deliver_briefing(self, cur, conn, briefing: dict, content: str, summary: str) -> dict:
        """Deliver a briefing through configured channels."""
        channels = briefing.get("delivery_channels", ["notification"])
        status = {}

        for channel in channels:
            try:
                if channel == "notification":
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                        (type, title, message, source, priority, is_read, created_at)
                        VALUES ('info', %s, %s, 'proactive_intelligence', 'normal', FALSE, NOW())
                        """,
                        (f"{briefing['name']}", content[:2000]),
                    )
                    conn.commit()
                    status["notification"] = "delivered"

                elif channel == "telegram":
                    # Will be picked up by notification forwarding
                    status["telegram"] = "queued_via_notification"

            except Exception as e:
                status[channel] = f"failed: {e}"

        # Also insert as chat message so it appears in the Chat tab
        try:
            cur.execute(
                """
                INSERT INTO ai_conversations
                (user_id, tool_name, conversation_id, message, response, model, metadata)
                VALUES (%s, 'archie-chat', %s, 'Daily Briefing', %s, 'system', %s::jsonb)
                """,
                (
                    briefing.get("user_id", 2),
                    f"briefing-{briefing['id']}-{datetime.now().strftime('%Y%m%d')}",
                    content,
                    json.dumps({"chat_mode": "briefing", "source": "proactive"}),
                ),
            )
            conn.commit()
            status["chat"] = "delivered"
        except Exception as be:
            logger.warning("Failed to insert briefing as chat message: %s", be)
            status["chat"] = f"failed: {be}"

        return status

    def generate_due_briefings(self):
        """Check for and generate any due briefings based on cron schedules."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT * FROM briefings WHERE is_active = TRUE")
            briefings = cur.fetchall()

            generated = 0
            for briefing in briefings:
                # Isolate each due-check: a failing _is_due query must not abort
                # the connection and poison every subsequent briefing's check
                # (the "Due briefings check failed: current transaction is
                # aborted" cascade observed 2026-05-30 20:06).
                try:
                    cur.execute("SAVEPOINT due_check")
                    due = self._is_due(briefing, cur)
                    cur.execute("RELEASE SAVEPOINT due_check")
                except Exception as e:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT due_check")
                    except Exception:
                        conn.rollback()
                    logger.warning(f"Due-check failed for briefing #{briefing.get('id')}: {e}")
                    continue
                if due:
                    cur.close()
                    conn.close()
                    self.generate_briefing(briefing["id"])
                    generated += 1
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.close()
            conn.close()
            return generated

        except Exception as e:
            logger.error(f"Due briefings check failed: {e}")
            return 0

    def _is_due(self, briefing: dict, cur) -> bool:
        """Check if a briefing should be generated now based on cron and last generation."""
        cron = briefing.get("schedule_cron", "")
        if not cron:
            return False

        # Simple cron check: parse "minute hour * * *" format
        parts = cron.split()
        if len(parts) < 2:
            return False

        try:
            target_minute = int(parts[0])
            target_hour = int(parts[1])
        except ValueError:
            return False

        now = datetime.now()
        if now.hour != target_hour or abs(now.minute - target_minute) > 5:
            return False

        # Check if already generated today
        cur.execute(
            """
            SELECT id FROM briefing_history
            WHERE briefing_id = %s AND generated_at > NOW() - INTERVAL '12 hours'
            LIMIT 1
            """,
            (briefing["id"],),
        )
        return cur.fetchone() is None


# ============================================================================
# ANOMALY DETECTOR
# ============================================================================


class AnomalyDetector:
    """SQL-based anomaly detection with threshold checking."""

    def check_all_rules(self) -> dict:
        """Check all active anomaly rules and create detections for triggered ones."""
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM anomaly_rules
            WHERE is_active = TRUE
              AND (last_checked_at IS NULL OR
                   last_checked_at < NOW() - make_interval(mins => check_interval_minutes))
            """
        )
        rules = cur.fetchall()

        checked = 0
        triggered = 0

        for rule in rules:
            try:
                is_triggered, current_val, threshold_val = self._check_rule(cur, rule)

                # Update last checked
                cur.execute(
                    "UPDATE anomaly_rules SET last_checked_at = NOW() WHERE id = %s",
                    (rule["id"],),
                )

                if is_triggered:
                    # Check cooldown
                    if rule.get("last_triggered_at"):
                        cooldown = rule.get("cooldown_minutes", 60)
                        cur.execute(
                            """
                            SELECT id FROM anomaly_detections
                            WHERE rule_id = %s AND created_at > NOW() - make_interval(mins => %s)
                            LIMIT 1
                            """,
                            (rule["id"], cooldown),
                        )
                        if cur.fetchone():
                            # Still in cooldown
                            conn.commit()
                            checked += 1
                            continue

                    # Create detection
                    cur.execute(
                        """
                        INSERT INTO anomaly_detections
                        (rule_id, severity, title, description, current_value, threshold_value, detection_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            rule["id"],
                            rule.get("severity", "warning"),
                            f"Anomaly: {rule['name']}",
                            rule.get("description", ""),
                            current_val,
                            threshold_val,
                            json.dumps({"rule_config": rule["rule_config"]}),
                        ),
                    )

                    cur.execute(
                        """
                        UPDATE anomaly_rules
                        SET last_triggered_at = NOW(),
                            consecutive_triggers = consecutive_triggers + 1
                        WHERE id = %s
                        """,
                        (rule["id"],),
                    )

                    # Create notification (admin-only — anomalies are system-level)
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                        (type, title, message, source, priority, visibility, is_read, created_at)
                        VALUES (%s, %s, %s, 'anomaly_detector', %s, 'admin', FALSE, NOW())
                        """,
                        (
                            ("warning" if rule.get("severity") != "critical" else "error"),
                            f"Anomaly: {rule['name']}",
                            f"{rule.get('description', '')} (Value: {current_val}, Threshold: {threshold_val})",
                            "high" if rule.get("severity") == "critical" else "normal",
                        ),
                    )

                    triggered += 1
                else:
                    # Reset consecutive triggers on non-trigger
                    if rule.get("consecutive_triggers", 0) > 0:
                        cur.execute(
                            "UPDATE anomaly_rules SET consecutive_triggers = 0 WHERE id = %s",
                            (rule["id"],),
                        )

                conn.commit()
                checked += 1

            except Exception as e:
                logger.error(f"Anomaly rule #{rule['id']} ({rule['name']}) check failed: {e}")
                conn.commit()

        cur.close()
        conn.close()

        return {"checked": checked, "triggered": triggered}

    def _check_rule(self, cur, rule: dict) -> tuple:
        """
        Check a single anomaly rule.

        Returns (is_triggered: bool, current_value: float, threshold_value: float)
        """
        config = rule["rule_config"]
        rule_type = rule["rule_type"]

        if rule_type == "sql_threshold":
            # Run the value query
            query = config.get("query", "")
            if not query:
                return False, 0, 0

            cur.execute(query)
            row = cur.fetchone()
            current_val = float(row.get("val", 0)) if row else 0

            # Get threshold
            threshold = config.get("threshold")
            if threshold is None:
                threshold_query = config.get("threshold_query", "")
                if threshold_query:
                    cur.execute(threshold_query)
                    t_row = cur.fetchone()
                    threshold = float(t_row.get("val", 0)) if t_row else 0
                else:
                    threshold = 0

            threshold = float(threshold)

            # Compare
            comparison = config.get("comparison", ">")
            if comparison == ">":
                return current_val > threshold, current_val, threshold
            elif comparison == "<":
                return current_val < threshold, current_val, threshold
            elif comparison == ">=":
                return current_val >= threshold, current_val, threshold
            elif comparison == "<=":
                return current_val <= threshold, current_val, threshold
            elif comparison == "==":
                return current_val == threshold, current_val, threshold
            else:
                return current_val > threshold, current_val, threshold

        return False, 0, 0


# ============================================================================
# REPORT ENGINE
# ============================================================================


class ReportEngine:
    """Generate scheduled reports with AI formatting."""

    def generate_report(self, report_id: int) -> Optional[str]:
        """Generate a scheduled report."""
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT * FROM scheduled_reports WHERE id = %s AND is_active = TRUE",
            (report_id,),
        )
        report = cur.fetchone()
        if not report:
            cur.close()
            conn.close()
            return None

        report_type = report["report_type"]
        config = report.get("report_config", {})

        # Gather data
        data = self._gather_report_data(cur, report_type, config)

        # Format with AI
        content = self._format_report(report, data)

        # Deliver
        self._deliver_report(cur, conn, report, content)

        cur.execute(
            "UPDATE scheduled_reports SET last_generated_at = NOW() WHERE id = %s",
            (report_id,),
        )
        conn.commit()
        cur.close()
        conn.close()

        return content

    def _gather_report_data(self, cur, report_type: str, config: dict) -> dict:
        """Gather data for a specific report type."""
        days = config.get("days", 7)

        if report_type == "email_summary":
            cur.execute(
                f"""
                SELECT ai_category, COUNT(*) as count
                FROM email_inbox
                WHERE created_at > NOW() - make_interval(days => %s)
                GROUP BY ai_category
                """,
                (days,),
            )
            categories = {r["ai_category"]: r["count"] for r in cur.fetchall() if r["ai_category"]}

            cur.execute(
                f"""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE is_read = FALSE) as unread
                FROM email_inbox
                WHERE created_at > NOW() - make_interval(days => %s)
                """,
                (days,),
            )
            totals = cur.fetchone()
            return {
                "categories": categories,
                "totals": dict(totals),
                "period_days": days,
            }

        elif report_type == "crm_activity":
            cur.execute(
                f"""
                SELECT COUNT(*) as total_customers,
                       COUNT(*) FILTER (WHERE created_at > NOW() - make_interval(days => %s)) as new_customers
                FROM crm_customers
                """,
                (days,),
            )
            return {"crm": dict(cur.fetchone()), "period_days": days}

        elif report_type == "system_health":
            cur.execute(
                """
                SELECT job_name,
                       COUNT(*) as cycles,
                       SUM(items_processed) as processed,
                       SUM(items_failed) as failed,
                       AVG(duration_ms)::integer as avg_ms
                FROM autonomy_loop_log
                WHERE created_at > NOW() - make_interval(days => %s)
                GROUP BY job_name
                """,
                (days,),
            )
            jobs = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT severity, COUNT(*) as count
                FROM anomaly_detections
                WHERE created_at > NOW() - make_interval(days => %s)
                GROUP BY severity
                """,
                (days,),
            )
            anomalies = {r["severity"]: r["count"] for r in cur.fetchall()}

            return {"jobs": jobs, "anomalies": anomalies, "period_days": days}

        return {"raw": "No data gatherer for report type: " + report_type}

    def _format_report(self, report: dict, data: dict) -> str:
        """Format report data into readable text using AI."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            prompt = f"""Format this raw data into a clean, professional report.
Report: {report['name']} ({report['report_type']})
Format: {report.get('output_format', 'text')}

Data:
{json.dumps(data, default=str, indent=2)}

Write a clear, concise report with sections and key metrics."""

            dispatcher = get_dispatcher()
            result = dispatcher.request_work("chat", prompt, "proactive_intelligence", timeout=120)
            if result.success:
                return result.response.strip()
            return json.dumps(data, indent=2, default=str)

        except Exception as e:
            logger.warning(f"Report formatting failed: {e}")
            return json.dumps(data, indent=2, default=str)

    def _deliver_report(self, cur, conn, report: dict, content: str):
        """Deliver a report through configured channels."""
        channels = report.get("delivery_channels", ["notification"])

        for channel in channels:
            try:
                if channel == "notification":
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                        (type, title, message, source, priority, is_read, created_at)
                        VALUES ('info', %s, %s, 'report_engine', 'normal', FALSE, NOW())
                        """,
                        (f"Report: {report['name']}", content[:2000]),
                    )
                    conn.commit()
            except Exception as e:
                logger.error(f"Report delivery via {channel} failed: {e}")

    def generate_due_reports(self):
        """Check and generate any due reports."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT * FROM scheduled_reports WHERE is_active = TRUE")
            reports = cur.fetchall()

            generated = 0
            for report in reports:
                if self._is_due(report, cur):
                    cur.close()
                    conn.close()
                    self.generate_report(report["id"])
                    generated += 1
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.close()
            conn.close()
            return generated

        except Exception as e:
            logger.error(f"Due reports check failed: {e}")
            return 0

    def _is_due(self, report: dict, cur) -> bool:
        """Check if a report should be generated now."""
        cron = report.get("schedule_cron", "")
        if not cron:
            return False

        parts = cron.split()
        if len(parts) < 2:
            return False

        try:
            target_minute = int(parts[0])
            target_hour = int(parts[1])
        except ValueError:
            return False

        now = datetime.now()
        if now.hour != target_hour or abs(now.minute - target_minute) > 5:
            return False

        # Check last generation
        last = report.get("last_generated_at")
        if last and (datetime.now() - last).total_seconds() < 43200:  # 12 hours
            return False

        return True
