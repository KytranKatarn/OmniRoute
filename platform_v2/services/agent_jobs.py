"""services/agent_jobs.py — Agent welfare/HR background jobs.

Extracted from agent_loop.py (Phase 5). Each job is a standalone function.
Registration with APScheduler happens via register_agent_welfare_jobs().

Jobs extracted:
  - agent_hr_tracker (Job: track_agent_hr, every 5min)
  - agent_ethics_monitoring (Job: ethics_monitoring, every 15min)
  - agent_training_tick (Job: process_training_tick, every 5min)
  - agent_welfare_recovery (Job: recover_idle_welfare, every 30min)
  - agent_idle_volunteering (Job: volunteer_idle_agents, every 5min)
  - agent_performance_rankings (Job: update_performance_rankings, every 15min)
"""

import json
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger("agent_loop")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_WELFARE_DEPARTMENT = "Human Resources & Culture"


def _log_cycle(
    job_name: str,
    items_processed: int,
    items_failed: int,
    duration_ms: int,
    details: dict = None,
    error_message: str = None,
):
    """Log an agent loop execution cycle to autonomy_loop_log."""
    status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
    try:
        from db import get_db

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
                _WELFARE_DEPARTMENT,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


def _log_governance_event(event_type, action, outcome, details=None, event_category="system", agent_id=None):
    """Log a governance event to the immutable audit log."""
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, action, outcome, details, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                event_type,
                event_category,
                agent_id,
                action,
                outcome,
                json.dumps(details or {}),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log governance event: {e}")


def _is_enabled(cur, config_key: str) -> bool:
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


def _create_hr_alert(cur, agent_id, alert_type, severity, title, message, details=None):
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
            _log_governance_event(
                "agent_welfare",
                f"alert_{alert_type}",
                "alert_created",
                {"agent_id": agent_id, "title": title},
            )

        return 1
    except Exception as e:
        logger.error(f"Failed to create HR alert: {e}")
        return 0


def _send_hr_telegram_alerts(cur, conn, flask_app):
    """Send unnotified critical/warning alerts via Telegram."""
    try:
        import asyncio

        # Find the running gateway instance
        gateway = flask_app.config.get("TELEGRAM_GATEWAY")
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


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------

# Reference to flask_app for Telegram access — set during registration
_flask_app = None


def track_agent_hr():
    """Aggregate task_execution_log into agent_daily_summary.
    Check for overwork, high error rates, and idle agents.
    Create alerts and send Telegram notifications for critical issues.
    Runs every 5 minutes.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor
    from services.agent_service import update_welfare

    start = time.time()
    processed = 0
    alerts_created = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if not _is_enabled(cur, "hr_tracker_enabled"):
            cur.close()
            conn.close()
            return

        today = datetime.utcnow().date()

        # 1. Aggregate today's task_execution_log into agent_daily_summary
        cur.execute(
            """
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
        """,
            (today,),
        )
        agent_stats = cur.fetchall()

        for stat in agent_stats:
            error_rate = 0
            if stat["total_tasks"] > 0:
                error_rate = round((stat["failed"] / stat["total_tasks"]) * 100, 2)

            # Calculate utilization
            hours_elapsed = max(
                (datetime.utcnow() - datetime.combine(today, datetime.min.time())).total_seconds() / 3600,
                0.1,
            )
            work_hours = stat["total_duration"] / 3_600_000  # ms -> hours
            utilization = min(round((work_hours / hours_elapsed) * 100, 2), 100)

            cur.execute(
                """
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
            """,
                (
                    stat["agent_id"],
                    today,
                    stat["total_tasks"],
                    stat["successful"],
                    stat["failed"],
                    stat["total_duration"],
                    round(float(stat["avg_duration"]), 1),
                    stat["models"] or [],
                    stat["modules"] or [],
                    stat["capabilities"] or [],
                    utilization,
                    error_rate,
                ),
            )
            processed += 1

        # 2. Check for alert conditions

        # 2a. High error rate (>30% with at least 5 tasks)
        cur.execute(
            """
            SELECT ads.agent_id, a.name, ads.error_rate_pct, ads.total_tasks
            FROM agent_daily_summary ads
            JOIN agents a ON a.id = ads.agent_id
            WHERE ads.summary_date = %s
              AND ads.error_rate_pct > 30
              AND ads.total_tasks >= 5
        """,
            (today,),
        )
        for row in cur.fetchall():
            alerts_created += _create_hr_alert(
                cur,
                row["agent_id"],
                "high_error_rate",
                "warning",
                f"{row['name']}: {row['error_rate_pct']}% error rate",
                f"Agent {row['name']} has a {row['error_rate_pct']}% error rate "
                f"across {row['total_tasks']} tasks today.",
                {
                    "error_rate": float(row["error_rate_pct"]),
                    "total_tasks": row["total_tasks"],
                },
            )

        # 2b. Overwork: >8h continuous work (total_duration_ms > 28800000)
        cur.execute(
            """
            SELECT ads.agent_id, a.name, ads.total_duration_ms
            FROM agent_daily_summary ads
            JOIN agents a ON a.id = ads.agent_id
            WHERE ads.summary_date = %s
              AND ads.total_duration_ms > 28800000
        """,
            (today,),
        )
        for row in cur.fetchall():
            hours = round(row["total_duration_ms"] / 3_600_000, 1)
            alerts_created += _create_hr_alert(
                cur,
                row["agent_id"],
                "overwork",
                "critical",
                f"{row['name']}: {hours}h continuous work",
                f"Agent {row['name']} has worked {hours} hours today. " f"Consider initiating a rest cycle.",
                {"work_hours": hours},
            )

            # Auto-initiate rest cycle for overworked agents
            cur.execute(
                """
                INSERT INTO agent_rest_cycles
                (agent_id, reason, started_at)
                SELECT %s, 'Automatic rest: exceeded 8h work threshold', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM agent_rest_cycles
                    WHERE agent_id = %s
                      AND started_at > NOW() - INTERVAL '1 hour'
                )
            """,
                (row["agent_id"], row["agent_id"]),
            )

        # 2c. Update emotional state based on workload
        cur.execute(
            """
            SELECT ads.agent_id, ads.utilization_pct, ads.error_rate_pct
            FROM agent_daily_summary ads
            WHERE ads.summary_date = %s
        """,
            (today,),
        )
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

        # 2d. Check proficiency degradation (fail too much -> degrade -> auto-train)
        degraded = _check_proficiency_degradation(cur, conn)
        alerts_created += degraded

        conn.commit()

        # 3. Send Telegram alerts for critical issues
        _send_hr_telegram_alerts(cur, conn, _flask_app)

        conn.commit()
        cur.close()
        conn.close()

        duration_ms = int((time.time() - start) * 1000)
        if processed > 0 or alerts_created > 0:
            logger.info(
                f"HR tracker: {processed} agents updated, " f"{alerts_created} alerts created ({duration_ms}ms)"
            )
        _log_cycle(
            "hr_tracker",
            processed,
            0,
            duration_ms,
            {"alerts_created": alerts_created},
        )

    except Exception as e:
        logger.error(f"HR tracker failed: {e}")
        _log_cycle(
            "hr_tracker",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def run_ethics_monitoring():
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
        checked = getattr(result, "agents_checked", 0) if result else 0
        issues = getattr(result, "issues_found", 0) if result else 0
        alerts = getattr(result, "alerts_created", 0) if result else 0
        if issues > 0 or alerts > 0:
            logger.info(f"C.R.E.E.D. ethics: {checked} checked, " f"{issues} issues, {alerts} alerts")
        _log_cycle(
            "ethics_monitoring",
            checked,
            issues,
            duration_ms,
            details={"issues": issues, "alerts": alerts},
        )
    except Exception as e:
        logger.error(f"C.R.E.E.D. ethics monitoring failed: {e}")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("ethics_monitoring", 0, 1, duration_ms, error_message=str(e))


def process_training_tick():
    """Check for completed training assignments and finalize them.

    When target_completion is reached:
    - Mark training as completed
    - Restore/boost confidence in agent_learning_log
    - Store failure_analysis as knowledge_base entry
    - Nudge emotional state positively
    - Send Telegram notification
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor
    from services.agent_service import add_skill, recover_idle

    start = time.time()
    completed = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find training assignments that have reached their target_completion
        cur.execute(
            """
            SELECT ta.id, ta.agent_id, ta.skill_name, ta.target_proficiency,
                   ta.current_proficiency, ta.failure_analysis, ta.degradation_triggered,
                   a.name as agent_name,
                   COALESCE(a.display_name, a.first_name || ' ' || a.last_name) as display_name
            FROM training_assignments ta
            JOIN agents a ON a.id = ta.agent_id
            WHERE ta.status = 'in_progress'
              AND ta.target_completion IS NOT NULL
              AND ta.target_completion <= NOW()
        """
        )
        ready = cur.fetchall()

        for t in ready:
            agent_id = t["agent_id"]
            skill_name = t["skill_name"]
            target_level = t["target_proficiency"]
            display_name = t["display_name"] or t["agent_name"]

            # Mark training as completed
            cur.execute(
                """
                UPDATE training_assignments
                SET status = 'completed', completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """,
                (t["id"],),
            )

            # Advance agent's proficiency level to target
            add_skill(agent_id, skill_name, level=target_level)

            # Boost confidence in agent_learning_log (cap at 1.0)
            cur.execute(
                """
                UPDATE agent_learning_log
                SET confidence = LEAST(1.0, confidence + 0.15),
                    successful_uses = successful_uses + 1,
                    last_used_at = NOW()
                WHERE agent_id = %s AND skill_name = %s
            """,
                (agent_id, skill_name),
            )

            # Store failure_analysis as knowledge_base entry for future reference
            if t["failure_analysis"]:
                cur.execute(
                    """
                    INSERT INTO knowledge_base
                    (title, content, source_type, tags, category, is_active, created_at)
                    VALUES (%s, %s, 'agent_learning', %s, 'training', TRUE, NOW())
                """,
                    (
                        f"Training Completion: {display_name} - {skill_name} Lv{target_level}",
                        f"Agent: {display_name}\nSkill: {skill_name}\nTarget Level: {target_level}\n\n"
                        f"Failure Analysis & Corrections:\n{t['failure_analysis']}",
                        json.dumps([t["agent_name"], skill_name, "training-completion"]),
                    ),
                )

            # Nudge emotional state positively
            recover_idle(agent_id, energy_boost=0.1, stress_reduction=0.1)

            completed += 1
            logger.info(
                f"Training completed: {display_name} finished {skill_name} " f"training, advanced to Lv{target_level}"
            )

        if completed > 0:
            conn.commit()

            # Send Telegram notification for completions
            try:
                gateway = _flask_app.config.get("TELEGRAM_GATEWAY") if _flask_app else None
                if gateway and gateway.is_running:
                    cur.execute(
                        """
                        SELECT telegram_id FROM telegram_users
                        WHERE is_authorized = TRUE AND user_id IS NOT NULL LIMIT 1
                    """
                    )
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
                                    text=text,
                                    parse_mode="Markdown",
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
        _log_cycle("training_tick", completed, 0, duration_ms)

    except Exception as e:
        logger.error(f"Training tick failed: {e}")
        _log_cycle(
            "training_tick",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def recover_idle_welfare():
    """Recover welfare for idle and resting agents.
    Runs every 30 minutes.
    - Idle (not dispatched in last hour): stress -0.15, energy +0.2
    - Resting (active rest cycle): stress -0.3, energy +0.4
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if not _is_enabled(cur, "hr_tracker_enabled"):
            cur.close()
            conn.close()
            return

        # Find agents with recent dispatches (last hour)
        cur.execute(
            """
            SELECT DISTINCT agent_name FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """
        )
        busy_names = {r["agent_name"] for r in cur.fetchall()}

        # Find resting agents
        cur.execute(
            """
            SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
        """
        )
        resting_ids = {r["agent_id"] for r in cur.fetchall()}

        # Get all active agents with current welfare
        cur.execute(
            """
            SELECT DISTINCT ON (a.id)
                   a.id, a.name, es.stress_level, es.energy_level
            FROM agents a
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.status = 'active'
            ORDER BY a.id, es.timestamp DESC NULLS LAST
        """
        )
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

            cur.execute(
                """
                INSERT INTO agent_emotional_state
                (agent_id, stress_level, energy_level, current_mood, trigger_event, timestamp)
                VALUES (%s, %s, %s,
                        CASE WHEN %s < 0.3 THEN 'relaxed'
                             WHEN %s < 0.6 THEN 'neutral'
                             ELSE 'focused' END,
                        'welfare_recovery', NOW())
            """,
                (aid, new_stress, new_energy, new_stress, new_stress),
            )
            recovered += 1

        conn.commit()
        duration_ms = int((time.time() - start) * 1000)
        if recovered > 0:
            logger.info(f"Welfare recovery: {recovered} agents recovered ({duration_ms}ms)")
        _log_cycle("welfare_recovery", recovered, 0, duration_ms)
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Welfare recovery error: {e}")
        _log_cycle(
            "welfare_recovery",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def volunteer_idle_agents():
    """Scan for idle agents and volunteer them at departments with pending work.
    Runs every 5 minutes.
    - Find departments with recent task failures
    - Find idle agents not in those departments
    - Create notifications for volunteering events
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        start = time.time()

        # Find departments with recent failures and no idle primaries
        cur.execute(
            """
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
        """
        )
        pending_jobs = cur.fetchall()

        if not pending_jobs:
            cur.close()
            conn.close()
            return

        # Find idle agents (not busy, not resting, active status)
        cur.execute(
            """
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
        """
        )
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
                _create_notification(
                    cur,
                    conn,
                    f"Fleet: {volunteer['name']} volunteering at {job['department']}",
                    "info",
                    {"agent": volunteer["name"], "department": job["department"]},
                )
                volunteered += 1
                idle_agents.remove(volunteer)

        conn.commit()
        duration_ms = int((time.time() - start) * 1000)
        if volunteered > 0:
            logger.info(f"Idle volunteering: {volunteered} agents volunteered ({duration_ms}ms)")
        _log_cycle("idle_volunteering", volunteered, 0, duration_ms)
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Idle volunteering error: {e}")


def _create_notification(cur, conn, title, ntype, details=None):
    """Create a system notification."""
    try:
        cur.execute(
            """
            INSERT INTO system_notifications
            (type, title, message, source, priority, visibility, is_read, created_at)
            VALUES (%s, %s, %s, 'agent_loop', 'low', 'admin', FALSE, NOW())
        """,
            (ntype, title, json.dumps(details or {})),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to create notification: {e}")


def update_performance_rankings():
    """Calculate comparative performance rankings per capability.
    Runs every 15 minutes.
    rank_score = (success_rate * 0.5) + (speed_score * 0.3) + (efficiency_score * 0.2)
    Minimum 10 tasks for reliable ranking -- below that, blend static proficiency.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        start = time.time()

        # Get per-agent per-capability aggregates
        cur.execute(
            """
            SELECT agent_id, capability,
                   COUNT(*) as tasks_completed,
                   ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::numeric, 4) as success_rate,
                   ROUND(AVG(duration_ms)::numeric) as avg_duration_ms,
                   ROUND(AVG(tokens_used)::numeric) as avg_tokens_used
            FROM task_execution_log
            WHERE agent_id IS NOT NULL AND capability IS NOT NULL
              AND created_at > NOW() - INTERVAL '7 days'
            GROUP BY agent_id, capability
        """
        )
        stats = cur.fetchall()

        # Group by capability
        by_capability = {}
        for row in stats:
            cap = row["capability"]
            if cap not in by_capability:
                by_capability[cap] = []
            by_capability[cap].append(row)

        updated = 0
        for capability, agents in by_capability.items():
            max_duration = max(float(a["avg_duration_ms"] or 0) for a in agents) or 1
            max_tokens = max(float(a["avg_tokens_used"] or 0) for a in agents) or 1

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
                    cur.execute(
                        """
                        SELECT proficiency_level FROM agent_skills
                        WHERE agent_id = %s AND skill_name = %s
                    """,
                        (agent["agent_id"], capability),
                    )
                    skill_row = cur.fetchone()
                    static_prof = float(skill_row["proficiency_level"] or 3) / 5.0 if skill_row else 0.5
                    rank_score = (static_prof * 0.7) + (rank_score * 0.3)

                scored.append(
                    {
                        **agent,
                        "rank_score": round(rank_score, 4),
                    }
                )

            scored.sort(key=lambda x: x["rank_score"], reverse=True)
            for position, agent in enumerate(scored, 1):
                cur.execute(
                    """
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
                """,
                    (
                        agent["agent_id"],
                        capability,
                        agent["tasks_completed"],
                        agent["success_rate"],
                        agent["avg_duration_ms"],
                        agent["avg_tokens_used"],
                        agent["rank_score"],
                        position,
                        agent["tasks_completed"],
                    ),
                )
                updated += 1

        conn.commit()
        duration_ms = int((time.time() - start) * 1000)
        if updated > 0:
            logger.info(f"Performance rankings: updated {updated} entries " f"across {len(by_capability)} capabilities")
            _log_cycle(
                "performance_rankings",
                updated,
                0,
                duration_ms,
                f"Updated {updated} entries",
            )
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Performance ranking error: {e}")


def _check_proficiency_degradation(cur, conn):
    """Check for agents with high failure rates and degrade their proficiency.

    Closed loop: dispatch -> fail -> degrade -> train (personalized) -> complete -> restore.
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
                now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
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
                    from tools.department_hq.services.bridge_dispatcher import get_dispatcher

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
            _create_hr_alert(
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
                f"Proficiency degradation: {display_name} Lv{current_level}->Lv{new_level} "
                f"on {capability} ({failure_rate}% failures). Training: {training_hours}h"
            )

        if degraded > 0:
            conn.commit()

    except Exception as e:
        logger.error(f"Proficiency degradation check failed: {e}")

    return degraded


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_agent_welfare_jobs(scheduler, flask_app):
    """Register all agent welfare/HR background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger

    global _flask_app
    _flask_app = flask_app

    def with_ctx(fn):
        """Wrap function to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn()

        wrapper.__name__ = fn.__name__
        return wrapper

    scheduler.add_job(
        with_ctx(track_agent_hr),
        trigger=IntervalTrigger(minutes=5),
        id="agent_hr_tracker",
        name="Agent Loop: HR Tracker",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(run_ethics_monitoring),
        trigger=IntervalTrigger(minutes=15),
        id="agent_ethics_monitoring",
        name="Agent Loop: Ethics Monitoring",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(process_training_tick),
        trigger=IntervalTrigger(minutes=5),
        id="agent_training_tick",
        name="Agent Loop: Training Progression Tick",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(recover_idle_welfare),
        trigger=IntervalTrigger(minutes=30),
        id="agent_welfare_recovery",
        name="Agent Loop: Welfare Recovery",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(volunteer_idle_agents),
        trigger=IntervalTrigger(minutes=5),
        id="agent_idle_volunteering",
        name="Agent Loop: Idle Volunteering",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(update_performance_rankings),
        trigger=IntervalTrigger(minutes=15),
        id="agent_performance_rankings",
        name="Agent Loop: Performance Rankings",
        replace_existing=True,
    )
