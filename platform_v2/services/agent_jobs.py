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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_TORONTO = ZoneInfo("America/Toronto")
from typing import Any, Optional

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
    """Submit unnotified critical/warning alerts to A.R.C.H.I.E. director report inbox."""
    try:
        from services.telegram_service import send_system as _hr_send
    except ImportError:
        return

    try:
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

        for alert in alerts:
            message = (
                f"{alert['message']}\n\n" f"Type: {alert['alert_type']} | Agent: {alert['agent_name'] or 'System'}"
            )
            try:
                # Interactive alert: ✓ Acknowledge (resolves the agent_alerts row) +
                # 📊 Details + 🔕 Snooze 24h (#alert-buttons). Sent DIRECT so the buttons
                # survive (the inbox relay strips reply_markup); keyed by the row id.
                # notified_telegram (below) still provides dedup for persistent conditions.
                from services.alert_actions_service import send_alert

                send_alert(
                    alert_key=f"hr_{alert['id']}",
                    title=f"HR Alert: {alert['title']}",
                    message=message,
                    actions=["ack", "details", "snooze"],
                    source_agent="K.I.N.",
                    source_department="Human Resources & Culture",
                )
                cur.execute(
                    "UPDATE agent_alerts SET notified_telegram = TRUE WHERE id = %s",
                    (alert["id"],),
                )
            except Exception as e:
                logger.error(f"Failed to route HR alert to inbox: {e}")

        conn.commit()

    except Exception as e:
        logger.error(f"HR Telegram alerts failed: {e}")


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------

# Reference to flask_app for Telegram access — set during registration
_flask_app = None


def _check_cluster_saturation(cur):
    """K.I.N. cluster advisory — PROACTIVE + ACTIONABLE (#375).

    When the hub sheds a burst of 7B dispatches under saturation, emit ONE
    consolidated root-cause advisory with recommended actions instead of N
    per-agent 'high error rate' pages. (Those false pages are already gone —
    sheds are excluded from the error rate — but the underlying saturation is a
    real condition worth surfacing ONCE, with the fix, rather than silently.)
    Self-dedups to one advisory / 2h (agent_id IS NULL; _create_hr_alert's own
    `= %s` dedup never matches NULL).
    """
    try:
        cur.execute(
            """SELECT 1 FROM agent_alerts
               WHERE agent_id IS NULL AND alert_type = 'cluster_saturation'
                 AND resolved = FALSE AND created_at > NOW() - INTERVAL '2 hours' LIMIT 1"""
        )
        if cur.fetchone():
            return 0

        cur.execute(
            """
            SELECT COUNT(*) AS sheds,
                   COUNT(DISTINCT agent_name) AS agents,
                   ARRAY_AGG(DISTINCT agent_name) AS agent_list
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '1 hour'
              AND success = FALSE
              AND (error_message ILIKE '%hub saturated%'
                   OR error_message ILIKE '%admission cap%'
                   OR error_message ILIKE '%shed to relieve%'
                   OR error_message ILIKE '%backpressure%')
            """
        )
        row = cur.fetchone() or {}
        sheds = row.get("sheds") or 0
        agents = row.get("agents") or 0
        # A real saturation BURST, not a one-off. Tunable.
        if sheds < 20 or agents < 2:
            return 0

        agent_list = [a for a in (row.get("agent_list") or []) if a][:8]
        who = ", ".join(agent_list)
        title = f"Hub 7B saturated — {sheds} dispatches shed across {agents} agents (1h)"
        message = (
            f"{sheds} dispatches were SHED across {agents} agents ({who}) in the last hour "
            f"because the hub's 8GB GPU cannot hold 7B under load. These are NOT agent errors "
            f"— it is the admission control shedding load to protect the hub.\n\n"
            f"Root cause: 7B fact_check/bias work piling onto the contended hub GPU while the "
            f"RTX Starships have headroom.\n\n"
            f"Recommended actions:\n"
            f"• Fleet → PLATFORM profile: give platform/interactive work GPU priority so 7B "
            f"prefers the Starships.\n"
            f"• Throttle the WTF fact_check/bias flood (welfare:backlog cap) if the backlog is high.\n"
            f"• Longer term: rebalance the 7B tier off the slow hub (Project #375).\n\n"
            f"Fleet tab: https://platform.kytranempowerment.com/tools/department-hq/#fleet"
        )
        return _create_hr_alert(
            cur,
            None,
            "cluster_saturation",
            "warning",
            title,
            message,
            {"sheds_1h": sheds, "agents": agents, "agent_list": agent_list},
        )
    except Exception as e:
        logger.warning("cluster saturation advisory failed: %s", e)
        return 0


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

        # Use EDT (America/Toronto) date so the welfare day aligns with
        # Kytran's actual calendar day.  Using UTC.date() rolls over at 8 pm
        # EDT (midnight UTC), making the overwork check go blind for agents
        # who accumulated hours before that point.
        today = datetime.now(_TORONTO).date()

        # Wall-clock REAL compute hours per agent today (KB #270628): interval-UNION,
        # not SUM(duration_ms), so concurrent dispatches are not counted multiple times;
        # window resets after the agent's last completed rest (post-rest cooldown) so a
        # just-rested agent cannot be re-flagged on stale hours. Single source of truth
        # shared with the K.I.N. welfare route. Computed once; used by 2b + 2c below.
        from services.agent_load_service import real_compute_hours_today

        hours_map = real_compute_hours_today(cur)

        # 1. Aggregate today's task_execution_log into agent_daily_summary.
        # WARNING: this SELECT is parameterized (the `= %s` for `today`), so psycopg2
        # scans the ENTIRE query string -- SQL comments included -- for percent signs.
        # EVERY literal percent must be doubled or psycopg2 reads it as a positional
        # placeholder and the whole HR job dies with "IndexError: tuple index out of
        # range" at step 1. Keep this SQL free of stray percent signs: the ILIKE
        # wildcards below are the only ones, doubled to `%%`. Do NOT put a bare percent
        # in the SQL comments either. (Regression from #2091; KB #268832 / #277249.)
        cur.execute(
            """
            SELECT agent_id,
                   COUNT(*) as total_tasks,
                   COUNT(CASE WHEN success = TRUE THEN 1 END) as successful,
                   COUNT(CASE WHEN success = FALSE THEN 1 END) as failed,
                   -- infra-backpressure "failures" (#4538 class): hub admission-control
                   -- sheds, queue timeouts, reaper kills -- NOT the agent's fault. Excluded
                   -- from the real error rate so a hub-saturation burst does not fire a storm
                   -- of false "high error rate" HR alerts (nor unfairly penalise welfare).
                   COUNT(CASE WHEN success = FALSE AND (
                       error_message ILIKE '%%hub saturated%%'
                       OR error_message ILIKE '%%admission cap%%'
                       OR error_message ILIKE '%%shed to relieve%%'
                       OR error_message ILIKE '%%backpressure%%'
                       OR error_message ILIKE '%%reaped%%'
                       OR error_message ILIKE '%%did not respond%%'
                       OR error_message ILIKE '%%auto-killed%%'
                       OR error_message ILIKE '%%queue timeout%%'
                       OR error_message ILIKE '%%timeout after%%'
                   ) THEN 1 END) as infra_failed,
                   COALESCE(SUM(duration_ms), 0) as total_duration,
                   COALESCE(AVG(duration_ms), 0) as avg_duration,
                   ARRAY_AGG(DISTINCT model_used) FILTER (WHERE model_used IS NOT NULL) as models,
                   ARRAY_AGG(DISTINCT module_source) FILTER (WHERE module_source IS NOT NULL) as modules,
                   ARRAY_AGG(DISTINCT capability) FILTER (WHERE capability IS NOT NULL) as capabilities
            FROM task_execution_log
            WHERE (created_at AT TIME ZONE 'America/Toronto')::date = %s
              AND agent_id IS NOT NULL
              AND COALESCE(module_source, '') != 'fleet_warmup'
            GROUP BY agent_id
        """,
            (today,),
        )
        agent_stats = cur.fetchall()

        for stat in agent_stats:
            # Error rate reflects the agent's OWN failures, EXCLUDING infra
            # backpressure sheds/timeouts (#4538 class) — those are the hub shedding
            # load, not agent error. Without this, a hub-saturation event shows every
            # 7B agent at ~100% "error rate" and fires a storm of false HR alerts (and
            # unfairly penalises them in the welfare formula, which reads error_rate_pct).
            infra_failed = stat.get("infra_failed") or 0
            real_failed = max(stat["failed"] - infra_failed, 0)
            real_total = max(stat["total_tasks"] - infra_failed, 0)
            error_rate = round((real_failed / real_total) * 100, 2) if real_total > 0 else 0

            # Calculate utilization
            hours_elapsed = max(
                (datetime.now(_TORONTO) - datetime.combine(today, datetime.min.time(), _TORONTO)).total_seconds()
                / 3600,
                0.1,
            )
            # Cap work_hours at hours_elapsed — sum of task durations can't exceed clock time
            work_hours = min(stat["total_duration"] / 3_600_000, hours_elapsed)
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

        # 2a.5 Cluster saturation advisory (proactive + correlated, #375). One
        # root-cause advisory when the hub sheds a 7B burst — replaces the storm
        # of per-agent 'high error rate' pages with a single actionable message.
        alerts_created += _check_cluster_saturation(cur)

        # 2b. Overwork — hours-based escalation
        #   8-12h + at task queue limit: K.I.N. workload monitor handles (auto 30-min rest)
        #   10h+: A.R.C.H.I.E. asks Kytran for approval via Telegram (upsert — no spam)
        #   12h+: A.R.C.H.I.E. auto-approves immediately and advises Kytran (C.R.E.E.D. compliance)
        # Overwork = REAL (non-internal) WALL-CLOCK compute hours today from hours_map
        # (KB #270628: interval-UNION, NOT SUM(duration_ms) — concurrent dispatches are
        # no longer counted N times, and the window resets after the agent's last
        # completed rest so a just-rested agent is not re-flagged on stale hours, which
        # ends the rest→reflag loop). 10h threshold; resting/off-shift agents skipped.
        _OVERWORK_SKIP_STATES = {"winding_down", "cooldown", "barracked", "off_duty"}
        overworked = [
            row for row in hours_map.values() if row["hours"] > 10.0 and row["shift_state"] not in _OVERWORK_SKIP_STATES
        ]
        for row in overworked:
            hours = float(row["hours"])
            is_auto_approve = hours >= 12.0

            alerts_created += _create_hr_alert(
                cur,
                row["agent_id"],
                "overwork",
                "critical" if is_auto_approve else "warning",
                f"{row['name']}: {hours}h continuous work",
                f"Agent {row['name']} has worked {hours} hours today. "
                + (
                    "A.R.C.H.I.E. enforcing 8h rest (C.R.E.E.D. compliance)."
                    if is_auto_approve
                    else "A.R.C.H.I.E. requesting Kytran approval."
                ),
                {"work_hours": hours, "auto_approved": is_auto_approve},
            )

            if is_auto_approve:
                # 12h: A.R.C.H.I.E. enforces immediately as COO — C.R.E.E.D. mandatory threshold
                try:
                    cur.execute(
                        """
                        INSERT INTO agent_rest_cycles
                            (agent_id, rest_type, reason, started_at, ended_at, initiated_by)
                        SELECT %s, 'coo_override',
                               'A.R.C.H.I.E. COO: 12h work threshold — C.R.E.E.D. mandatory rest',
                               NOW(), NOW() + INTERVAL '8 hours', 'archie_coo'
                        WHERE NOT EXISTS (
                            -- block on ANY active rest cycle (overlap fix); the old 30-min
                            -- window let a long (8h) rest started >30min ago slip past so a
                            -- second cycle stacked and the agent was over-benched.
                            SELECT 1 FROM agent_rest_cycles
                            WHERE agent_id = %s
                              AND (ended_at IS NULL OR ended_at > NOW())
                        )
                        """,
                        (row["agent_id"], row["agent_id"]),
                    )
                    from services.agent_service import transition_shift_state as _ts

                    _ts(
                        row["agent_id"],
                        "winding_down",
                        "A.R.C.H.I.E. COO: 12h welfare threshold — C.R.E.E.D. mandatory rest",
                    )
                    cur.execute(
                        """UPDATE agent_budgets SET current_task_count=0,
                              last_task_reset_at=NOW(),
                              task_reset_reason='A.R.C.H.I.E. COO 8h rest — C.R.E.E.D.',
                              task_reset_by='archie_coo', updated_at=NOW()
                           WHERE agent_id=%s""",
                        (row["agent_id"],),
                    )
                    # Redelegation — "give another agent a chance" (owner directive).
                    # winding_down does NOT trigger find_replacement (only cooldown does,
                    # agent_service.transition_shift_state), so a benched specialist would
                    # leave its department uncovered for the full 8h rest. Proactively wake
                    # a same-department barracked/off_duty peer so a stand-in is ready. The
                    # dispatcher also excludes the rested agent and wakes a skilled specialist
                    # on demand, so a None here is fine — this just front-loads the hand-off.
                    # Best-effort: a replacement failure must never break COO enforcement.
                    try:
                        cur.execute("SELECT department FROM agents WHERE id=%s", (row["agent_id"],))
                        _dept_row = cur.fetchone()
                        if _dept_row:
                            from services.agent_service import find_replacement as _find_repl

                            _repl = _find_repl(row["agent_id"], _dept_row["department"], _cur=cur)
                            if _repl:
                                logger.info(
                                    "[A.R.C.H.I.E. COO] Redelegated %s's duties to %s during 8h rest",
                                    row["name"],
                                    _repl.get("name"),
                                )
                            else:
                                logger.info(
                                    "[A.R.C.H.I.E. COO] No barracked peer for %s; dispatcher will "
                                    "redelegate on demand",
                                    row["name"],
                                )
                    except Exception as _repl_err:
                        logger.warning(
                            "[A.R.C.H.I.E. COO] replacement lookup failed for %s: %s", row["name"], _repl_err
                        )
                    # Close any pending approval queue row
                    cur.execute(
                        """UPDATE autonomy_approval_queue
                              SET status='approved', approved_at=NOW(),
                                  execution_result=%s::jsonb, updated_at=NOW()
                            WHERE action_type='welfare_rest_8h'
                              AND action_data->>'agent_id' = %s AND status='pending'""",
                        (
                            json.dumps({"approved_by": "A.R.C.H.I.E. (COO)", "reason": "12h threshold — C.R.E.E.D."}),
                            str(row["agent_id"]),
                        ),
                    )
                    # C.R.E.E.D. governance log. details is JSONB — the previous code
                    # passed a plain string here, raising 'invalid input syntax for type
                    # json' which aborted the whole COO enforcement txn (KB #270619). Human
                    # text now goes in reason (text); structured payload in details (jsonb).
                    cur.execute(
                        """INSERT INTO governance_audit_log
                               (agent_id, event_category, event_type, action, reason, details, timestamp)
                           VALUES (%s,'creed_compliance','coo_welfare_override','archie_coo',%s,%s::jsonb,NOW())""",
                        (
                            row["agent_id"],
                            f"A.R.C.H.I.E. COO enforced 8h rest for {row['name']} ({hours}h worked — 12h threshold)",
                            json.dumps({"agent": row["name"], "hours": hours, "threshold_hours": 12, "rest_hours": 8}),
                        ),
                    )
                    # Telegram: A.R.C.H.I.E. advises Kytran of her decision
                    try:
                        from services.telegram_service import send_info as _archie_coo_send

                        _archie_coo_send(
                            title="⚖️ A.R.C.H.I.E. — Agent Welfare Decision",
                            message=(
                                f"I have approved *{row['name']}*'s 8-hour rest cycle as COO.\n\n"
                                f"{row['name']} has worked *{hours} hours* today, reaching the C.R.E.E.D. "
                                f"mandatory rest threshold.\n\n"
                                f"Agent is winding down — returning to full duty in 8 hours. "
                                f"Decision logged in C.R.E.E.D. governance records.\n\n"
                                f"_— A.R.C.H.I.E., COO_"
                            ),
                            source_agent="A.R.C.H.I.E.",
                            source_department="Executive Office",
                        )
                    except Exception as _tg_err:
                        logger.warning("[A.R.C.H.I.E. COO] Telegram notify failed: %s", _tg_err)
                    logger.info("[A.R.C.H.I.E. COO] Enforced 8h rest for %s (%sh)", row["name"], hours)
                except Exception as _coo_err:
                    logger.error("[A.R.C.H.I.E. COO] Rest enforcement failed for %s: %s", row["name"], _coo_err)

            else:
                # 10h-12h: A.R.C.H.I.E. requests Kytran approval (upsert — Telegram only on new alert)
                _queue_id = None
                _is_new_alert = False
                try:
                    _action_data = json.dumps({"agent_id": row["agent_id"], "agent_name": row["name"], "hours": hours})
                    _reason = (
                        f"Agent {row['name']} worked {hours}h — A.R.C.H.I.E. requesting approval. "
                        f"Auto-enforced at 12h."
                    )
                    cur.execute(
                        """SELECT id FROM autonomy_approval_queue
                           WHERE action_type='welfare_rest_8h'
                             AND action_data->>'agent_id'=%s AND status='pending'
                           ORDER BY created_at DESC LIMIT 1""",
                        (str(row["agent_id"]),),
                    )
                    _existing = cur.fetchone()
                    if _existing:
                        cur.execute(
                            """UPDATE autonomy_approval_queue
                                  SET action_data=%s::jsonb, reason=%s,
                                      expires_at=NOW()+INTERVAL '8 hours', updated_at=NOW()
                                WHERE id=%s""",
                            (_action_data, _reason, _existing["id"]),
                        )
                        _queue_id = _existing["id"]
                        _is_new_alert = False
                    else:
                        cur.execute(
                            """INSERT INTO autonomy_approval_queue
                                   (action_type,action_data,tier,priority,requested_by,reason,expires_at)
                               VALUES ('welfare_rest_8h',%s::jsonb,2,1,'A.R.C.H.I.E.',%s,NOW()+INTERVAL '8 hours')
                               RETURNING id""",
                            (_action_data, _reason),
                        )
                        _qr = cur.fetchone()
                        _queue_id = _qr["id"] if _qr else None
                        _is_new_alert = True
                except Exception as _qi_err:
                    logger.warning("[A.R.C.H.I.E.] Approval queue upsert failed: %s", _qi_err)
                    _is_new_alert = True

                if _is_new_alert:
                    try:
                        from services.telegram_service import send_with_buttons as _welfare_buttons

                        _rest_cb = (
                            f"welfare_rest8h_{row['agent_id']}_{_queue_id}"
                            if _queue_id
                            else f"welfare_rest8h_{row['agent_id']}"
                        )
                        _dismiss_cb = (
                            f"welfare_dismiss_{_queue_id}" if _queue_id else f"welfare_dismiss_{row['agent_id']}"
                        )
                        _welfare_buttons(
                            category="agent",
                            title="⚠️ A.R.C.H.I.E. — Welfare Approval Needed",
                            message=(
                                f"*{row['name']}* has worked *{hours} hours* today.\n\n"
                                f"K.I.N. is monitoring. At *12 hours* I will enforce an 8h rest under C.R.E.E.D. authority.\n\n"
                                f"You may approve early to protect the agent's wellbeing.\n\n"
                                f"_Also visible in DHQ → Approvals tab._"
                            ),
                            buttons=[
                                {"text": "✅ Grant 8h Rest Now", "callback_data": _rest_cb},
                                {
                                    "text": "⏰ Continue Monitoring",
                                    "callback_data": f"welfare_snooze_{row['agent_id']}",
                                },
                                {"text": "🔕 Dismiss", "callback_data": _dismiss_cb},
                            ],
                            source_agent="A.R.C.H.I.E.",
                            source_department="Executive Office",
                        )
                    except Exception as _ow_err:
                        logger.warning("[A.R.C.H.I.E.] Welfare approval Telegram failed: %s", _ow_err)

        # 2c. Update emotional state based on workload + hours worked + rest recovery
        cur.execute(
            """
            SELECT ads.agent_id, ads.utilization_pct, ads.error_rate_pct,
                   -- hours-worked-today comes from hours_map (KB #270628 interval-union),
                   -- NOT ads.total_duration_ms (raw SUM inflates under concurrency)
                   (SELECT COUNT(*) FROM agent_rest_cycles arc
                    WHERE arc.agent_id = ads.agent_id
                      AND arc.started_at <= NOW()
                      AND (arc.ended_at IS NULL OR arc.ended_at > NOW())) AS is_resting,
                   -- FIX-5d (KB #270619): real 1h token + duration load so base stress
                   -- uses the shared welfare_load formula, not duration-utilization.
                   (SELECT COALESCE(SUM(tl.tokens_used), 0)
                      FROM task_execution_log tl
                     WHERE tl.agent_id = ads.agent_id
                       AND tl.created_at >= NOW() - INTERVAL '1 hour') AS toks_1h,
                   (SELECT COALESCE(SUM(tl.duration_ms), 0)
                      FROM task_execution_log tl
                     WHERE tl.agent_id = ads.agent_id
                       AND tl.created_at >= NOW() - INTERVAL '1 hour') AS dur_ms_1h,
                   -- Fix #C (C.R.E.E.D. accounting): 24h token sum for the budget
                   -- overwork term, same shape as toks_1h above but a wider window.
                   (SELECT COALESCE(SUM(tl.tokens_used), 0)
                      FROM task_execution_log tl
                     WHERE tl.agent_id = ads.agent_id
                       AND tl.created_at >= NOW() - INTERVAL '24 hours') AS tokens_24h,
                   (SELECT ab.token_limit_per_day
                      FROM agent_budgets ab
                     WHERE ab.agent_id = ads.agent_id) AS token_limit
            FROM agent_daily_summary ads
            WHERE ads.summary_date = %s
        """,
            (today,),
        )
        for row in cur.fetchall():
            hours = float((hours_map.get(row["agent_id"]) or {}).get("hours", 0) or 0)
            is_resting = int(row["is_resting"] or 0) > 0

            # KB #270628 convergence: stress/energy from the ONE shared welfare_load
            # formula — token load + failure rate + hours-on-duty fatigue + rest
            # recovery. Previously hr_tracker hand-rolled the hours/rest terms here, so
            # the K.I.N. decay refresh (token-only) stripped them every cycle and the two
            # writers fought (the 0.9↔0.6 thrash that stranded V.E.R.I.F.Y./B.I.A.S./
            # K.I.N.). Now all three writers call the same function with hours, so no
            # writer can strip another's term — no staleness gate needed. error_rate_pct
            # (0–100) maps to failure_rate via failures=error_rate_pct, total=100.
            from services.welfare_load import compute_token_load, stress_energy_from_load

            _load = compute_token_load(row.get("toks_1h"), row.get("dur_ms_1h"), row.get("token_limit"))

            # Fix #C: token-budget overwork term. token_util = tokens_24h / daily
            # budget; 0.0 (no budget configured) is the safe "unknown" no-op.
            _token_limit = row.get("token_limit")
            if _token_limit and float(_token_limit) > 0:
                _token_util = float(row.get("tokens_24h") or 0) / float(max(_token_limit, 1))
            else:
                _token_util = 0.0

            stress, energy = stress_energy_from_load(
                _load,
                failures=float(row["error_rate_pct"] or 0),
                total=100.0,
                hours_on_duty=hours,
                is_resting=is_resting,
                token_util=_token_util,
            )

            # Mood reflects combined state
            if is_resting:
                mood = "recovering"
            elif stress > 0.85:
                mood = "exhausted" if hours >= 8 else "stressed"
            elif stress > 0.6:
                mood = "stressed"
            elif stress > 0.4:
                mood = "focused"
            else:
                mood = "relaxed"

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
        # Pass issues in details only — not as items_failed, which would
        # surface C.R.E.E.D. welfare flags as system errors in the ops header.
        _log_cycle(
            "ethics_monitoring",
            checked,
            0,
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

            # Route training completions to A.R.C.H.I.E. director report inbox
            try:
                from services.telegram_service import send_agent as _training_send

                for t in ready:
                    dn = t["display_name"] or t["agent_name"]
                    _training_send(
                        title=f"Training Complete: {dn}",
                        message=(f"{dn} finished {t['skill_name']} training, " f"now at Lv{t['target_proficiency']}."),
                        source_agent="K.I.N.",
                        source_department="Human Resources & Culture",
                        source_module="agent_jobs",
                    )
            except Exception as e:
                logger.warning(f"Failed to route training completion to inbox: {e}")

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
                # Only notify on state change — skip if same assignment was
                # already notified within the last 30 minutes to prevent
                # notification spam from the 5-min job cycle.
                notif_title = f"Fleet: {volunteer['name']} volunteering at {job['department']}"
                cur.execute(
                    """SELECT 1 FROM system_notifications
                       WHERE title = %s
                         AND created_at > NOW() - INTERVAL '30 minutes'
                       LIMIT 1""",
                    (notif_title,),
                )
                if not cur.fetchone():
                    _create_notification(
                        cur,
                        conn,
                        notif_title,
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
# Observability jobs — Project #261 task #2101
# Alerts flow through agent_alerts; track_agent_hr (5m) picks them up and
# pushes to Telegram via _send_hr_telegram_alerts, so no separate sender.
# ---------------------------------------------------------------------------


def check_queue_exhaustion():
    """DHQ observer: alert when an agent sits at/above its task_queue_limit.

    Runs every 10 minutes. _create_hr_alert dedups at 1h, so a stuck agent
    produces at most one warning per hour (matches the "stays that way for
    >30min" requirement — second firing inside the 10-min cadence confirms
    persistence, dedup keeps signal clean).
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    alerts_created = 0
    checked = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.id, a.name, a.display_name, a.department,
                b.current_task_count, b.task_queue_limit
            FROM agent_budgets b
            JOIN agents a ON a.id = b.agent_id
            WHERE b.task_queue_limit > 0
              AND b.current_task_count >= b.task_queue_limit
              AND a.shift_state = 'active'
            """
        )
        rows = cur.fetchall()
        checked = len(rows)

        for row in rows:
            display = row["display_name"] or row["name"]
            created = _create_hr_alert(
                cur,
                row["id"],
                "queue_exhaustion",
                "warning",
                f"{display}: task queue full ({row['current_task_count']}/{row['task_queue_limit']})",
                (
                    f"Agent {display} ({row['department']}) is at or above task queue limit "
                    f"({row['current_task_count']}/{row['task_queue_limit']}). Downstream "
                    f"dispatches to this agent will block until the queue drains."
                ),
                {
                    "department": row["department"],
                    "current_task_count": row["current_task_count"],
                    "task_queue_limit": row["task_queue_limit"],
                },
            )
            alerts_created += created

        if alerts_created:
            conn.commit()

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "check_queue_exhaustion",
            checked,
            0,
            duration_ms,
            details={"exhausted_agents": checked, "alerts_created": alerts_created},
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("check_queue_exhaustion failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("check_queue_exhaustion", 0, 1, duration_ms, error_message=str(e))


def check_counter_drift():
    """Reconcile agent_budgets.current_task_count against bridge_jobs reality.

    Runs hourly. For each agent, compare stored counter to the actual count
    of pending/running/queued jobs in bridge_jobs. If |drift| > 3, alert —
    persistent drift (>1h) self-confirms via re-firing + dedup.

    This job DETECTS drift only. It does NOT auto-correct the counter —
    that is a deliberate separation so the fix lives with the decrement
    bug (sibling task) and this observer stays idempotent and safe.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    DRIFT_THRESHOLD = 3

    start = time.time()
    alerts_created = 0
    max_drift = 0
    drifted = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # bridge_jobs keys by agent_name, not agent_id — join on name.
        # Active-work definition MUST match reconcile_task_counters:
        # anything NOT terminal still holds an in-flight slot (including
        # pending_approval, which occupies the queue until approved/denied).
        # Using a narrower IN-list caused false-positive drift alerts —
        # e.g. Pixel with 5 month-old pending_approval jobs that the
        # canonical reconciliation correctly recognises as real load.
        cur.execute(
            """
            WITH active_bj AS (
                SELECT agent_name, COUNT(*) AS live_count
                FROM bridge_jobs
                WHERE status NOT IN ('completed', 'failed', 'cancelled')
                  AND agent_name IS NOT NULL
                GROUP BY agent_name
            )
            SELECT
                a.id, a.name, a.display_name, a.department,
                b.current_task_count,
                COALESCE(active_bj.live_count, 0) AS live_count,
                b.current_task_count - COALESCE(active_bj.live_count, 0) AS drift
            FROM agent_budgets b
            JOIN agents a ON a.id = b.agent_id
            LEFT JOIN active_bj ON active_bj.agent_name = a.name
            WHERE a.shift_state = 'active'
              AND ABS(b.current_task_count - COALESCE(active_bj.live_count, 0)) > %s
            """,
            (DRIFT_THRESHOLD,),
        )
        rows = cur.fetchall()
        drifted = len(rows)

        for row in rows:
            display = row["display_name"] or row["name"]
            drift = row["drift"]
            max_drift = max(max_drift, abs(drift))
            direction = "over-reports" if drift > 0 else "under-reports"

            created = _create_hr_alert(
                cur,
                row["id"],
                "queue_counter_drift",
                "warning",
                f"{display}: task counter drift ({drift:+d})",
                (
                    f"agent_budgets.current_task_count={row['current_task_count']} but "
                    f"bridge_jobs shows {row['live_count']} active jobs for {display} "
                    f"({row['department']}). Counter {direction} reality by {abs(drift)}. "
                    f"Counter auto-corrected to {row['live_count']}. Investigate decrement path to prevent recurrence."
                ),
                {
                    "department": row["department"],
                    "stored_count": row["current_task_count"],
                    "live_count": row["live_count"],
                    "drift": drift,
                },
            )
            alerts_created += created

            # Self-correct: align stored counter to bridge_jobs reality.
            # The alert notifies Kytran; this correction prevents cascading effects
            # (welfare gates, capacity limits) from acting on stale data.
            cur.execute(
                "UPDATE agent_budgets SET current_task_count = %s, updated_at = NOW() WHERE agent_id = %s",
                (row["live_count"], row["id"]),
            )

        if drifted:
            conn.commit()

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "check_counter_drift",
            drifted,
            0,
            duration_ms,
            details={
                "drifted_agents": drifted,
                "alerts_created": alerts_created,
                "max_drift": max_drift,
                "threshold": DRIFT_THRESHOLD,
            },
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("check_counter_drift failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("check_counter_drift", 0, 1, duration_ms, error_message=str(e))


def department_welfare_digest():
    """K.I.N. daily digest: per-department welfare roll-up.

    Project #261 task #1933. Surfaces get_department_welfare_summary()
    so K.I.N. (and Kytran via Telegram) sees the aggregate state
    without having to pull it. Fires a warning alert only when a
    department has avg_stress > 0.5 or >= 1 agent at risk — quiet
    days stay quiet.
    """
    from services.agent_service import get_department_welfare_summary

    start = time.time()
    alerts_created = 0
    at_risk_depts = []

    try:
        summary = get_department_welfare_summary() or []

        flagged = [d for d in summary if float(d.get("avg_stress") or 0) > 0.5 or (d.get("agents_at_risk") or 0) >= 1]

        if flagged:
            from db import get_db
            from psycopg2.extras import RealDictCursor

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            preview_parts = []
            for d in flagged[:6]:
                preview_parts.append(
                    f"{d['department']} (stress={d['avg_stress']}, "
                    f"at_risk={d['agents_at_risk']}/{d['total_agents']}, "
                    f"mood={d.get('dominant_mood') or 'unknown'})"
                )
            preview = "; ".join(preview_parts)
            if len(flagged) > 6:
                preview += f" (+{len(flagged) - 6} more)"

            alerts_created = _create_hr_alert(
                cur,
                None,
                "department_welfare_risk",
                "warning",
                f"K.I.N. welfare digest: {len(flagged)} department(s) elevated",
                (
                    f"Departments with stress > 0.5 or agents-at-risk: {preview}. "
                    "Review welfare state before next heavy-dispatch window."
                ),
                {"flagged_departments": flagged, "all_departments": summary},
            )
            if alerts_created:
                conn.commit()
            at_risk_depts = [d["department"] for d in flagged]
            cur.close()
            conn.close()

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "department_welfare_digest",
            len(summary),
            0,
            duration_ms,
            details={
                "departments_total": len(summary),
                "departments_flagged": len(flagged),
                "at_risk_departments": at_risk_depts,
                "alerts_created": alerts_created,
            },
        )
    except Exception as e:
        logger.exception("department_welfare_digest failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("department_welfare_digest", 0, 1, duration_ms, error_message=str(e))


def ollama_lifecycle_telemetry():
    """Snapshot Ollama's loaded-model state every 5 min.

    Project #261 task #1898. Ollama already handles load-on-dispatch
    (via ensure_model_ready) and idle unload (OLLAMA_KEEP_ALIVE=5m,
    OLLAMA_MAX_LOADED_MODELS=3) on its own. This job does NOT enforce
    eviction — it observes. It logs the live state so we have history,
    and raises a warning if a model's KEEP_ALIVE expired >2m ago but
    it's still resident (= Ollama's lifecycle has stalled).
    """
    from services.agent_models import snapshot_ollama_lifecycle

    start = time.time()
    alerts_created = 0

    try:
        snap = snapshot_ollama_lifecycle()
        expired = snap.get("expired_still_loaded", [])

        if expired:
            from db import get_db
            from psycopg2.extras import RealDictCursor

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            names = ", ".join(m["name"] for m in expired)
            alerts_created = _create_hr_alert(
                cur,
                None,
                "ollama_keep_alive_stall",
                "warning",
                f"Ollama KEEP_ALIVE stalled on {len(expired)} model(s)",
                (
                    f"Models past their KEEP_ALIVE window but still loaded: {names}. "
                    "This points at the Ollama daemon, not at dispatch — inspect "
                    "systemctl status ollama and recent /api/generate logs."
                ),
                {"expired": expired},
            )
            if alerts_created:
                conn.commit()
            cur.close()
            conn.close()

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "ollama_lifecycle_telemetry",
            snap["models_loaded"],
            0,
            duration_ms,
            details={
                "models_loaded": snap["models_loaded"],
                "total_vram_gb": snap["total_vram_gb"],
                "total_ram_gb": snap["total_ram_gb"],
                "models": [
                    {
                        "name": m["name"],
                        "vram_gb": m["vram_gb"],
                        "seconds_remaining": m["seconds_remaining"],
                    }
                    for m in snap["models"]
                ],
                "expired_count": len(expired),
                "alerts_created": alerts_created,
            },
        )
    except Exception as e:
        logger.exception("ollama_lifecycle_telemetry failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("ollama_lifecycle_telemetry", 0, 1, duration_ms, error_message=str(e))


def check_understaffed_capabilities():
    """K.I.N. daily: which capabilities have no Lv4+ dispatchable agent?

    Runs once a day (09:00 UTC). A capability is "understaffed" when NO
    active agent with proficiency_level >= 4 is dispatchable (i.e., below
    their task_queue_limit). Emits one system-level alert with the full
    list so HR sees it as a single digest, not N per-capability pages.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    alerts_created = 0
    gaps = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            WITH all_capabilities AS (
                -- Normalize to snake_case (same as _list_current_capability_gaps)
                SELECT DISTINCT lower(replace(skill_name, ' ', '_')) AS skill_name
                FROM agent_skills
                WHERE proficiency_level >= 4
            ),
            staffed AS (
                SELECT DISTINCT lower(replace(s.skill_name, ' ', '_')) AS skill_name
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                LEFT JOIN agent_budgets b ON b.agent_id = a.id
                WHERE s.proficiency_level >= 4
                  AND a.shift_state = 'active'
                  AND (
                      b.agent_id IS NULL
                      OR b.current_task_count < COALESCE(b.task_queue_limit, 100)
                  )
            )
            SELECT skill_name
            FROM all_capabilities
            WHERE skill_name NOT IN (SELECT skill_name FROM staffed)
            ORDER BY skill_name
            """
        )
        gap_rows = cur.fetchall()
        gaps = len(gap_rows)

        if gaps > 0:
            gap_list = [r["skill_name"] for r in gap_rows]
            preview = ", ".join(gap_list[:12])
            if gaps > 12:
                preview += f" (+{gaps - 12} more)"

            # agent_id=NULL for system-level digest
            alerts_created = _create_hr_alert(
                cur,
                None,
                "understaffed_capabilities",
                "warning",
                f"K.I.N. digest: {gaps} capabilities lack a Lv4+ dispatchable agent",
                (
                    f"Capabilities with no Lv4+ agent currently dispatchable: {preview}. "
                    "Consider reactivating a decommissioned specialist or proposing a "
                    "new acronym agent via the hire workflow."
                ),
                {"gap_count": gaps, "capabilities": gap_list},
            )
            if alerts_created:
                conn.commit()

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "check_understaffed_capabilities",
            gaps,
            0,
            duration_ms,
            details={"understaffed_capabilities": gaps, "alerts_created": alerts_created},
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("check_understaffed_capabilities failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("check_understaffed_capabilities", 0, 1, duration_ms, error_message=str(e))


# ---------------------------------------------------------------------------
# K.I.N. Hire Proposal Generation (#2102)
# ---------------------------------------------------------------------------
# Daily ~09:05 UTC, right after agent_understaffed_digest. Re-runs the same
# WITH clause used by check_understaffed_capabilities (single source of truth),
# then for each gap generates a shortlist + best-effort narrative and calls
# hiring_service.propose_for_gap.

KIN_AGENT_ID = 145  # prior-session exploration confirmed agents.id for K.I.N.
MAX_PROPOSALS_PER_RUN = 10


def _list_current_capability_gaps() -> list[dict[str, Any]]:
    """Re-run the same WITH clause check_understaffed_capabilities uses.

    Single source of truth — avoids cross-table dependency on
    system_notifications / autonomy_loop_log for the gap list.

    #5187: gaps are DEMAND-GATED — a capability only counts as a gap if it saw
    real inference dispatch in the last 30 days. Measured 2026-08-17, the
    ungated list was 104 capabilities and EXACTLY ZERO of them had a single
    real dispatch in 30 days: pure skill-inventory noise (Lv4+ skill rows left
    behind on decommissioned/inactive agents for work nobody requests). That
    noise is why skipped_empty_shortlist ran at 100% for weeks — and had a
    demanded capability ever genuinely lost its last agent, the signal would
    have been indistinguishable from the noise. With the gate, a surviving gap
    means "work is actually arriving and nobody active can take it".
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            WITH all_capabilities AS (
                -- Normalize to snake_case so decommissioned agents' Title Case skills
                -- (e.g. "Infrastructure as Code") match active agents' snake_case skills
                -- (e.g. "infrastructure_as_code"). Without this, every Title Case skill
                -- from a decommissioned human agent appears as a false-positive gap.
                SELECT DISTINCT lower(replace(skill_name, ' ', '_')) AS skill_name
                FROM agent_skills
                WHERE proficiency_level >= 4
            ),
            staffed AS (
                SELECT DISTINCT lower(replace(s.skill_name, ' ', '_')) AS skill_name
                FROM agent_skills s
                JOIN agents a ON a.id = s.agent_id
                LEFT JOIN agent_budgets b ON b.agent_id = a.id
                WHERE s.proficiency_level >= 4
                  AND a.shift_state = 'active'
                  AND (b.agent_id IS NULL
                       OR b.current_task_count < COALESCE(b.task_queue_limit, 100))
            ),
            demand AS (
                -- Real inference only — same exclude-list the Token Economy /
                -- A.R.M.A.D.A. surfaces use to split markers from real work.
                SELECT DISTINCT capability
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '30 days'
                  AND worker_type IS NOT NULL
                  AND lower(COALESCE(model_used, '')) NOT IN
                      ('bridge-managed', 'internal', 'batch', 'browser', 'comfyui', '')
            )
            SELECT skill_name AS capability
            FROM all_capabilities
            WHERE skill_name NOT IN (SELECT skill_name FROM staffed)
              AND skill_name IN (SELECT capability FROM demand)
            ORDER BY skill_name
            """
        )
        return [
            {
                "capability": r["capability"],
                "gap_reason": (
                    f"No active Lv4+ dispatchable agent for '{r['capability']}' "
                    "despite real dispatch demand in the last 30 days"
                ),
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def _generate_hire_narrative(gap: dict[str, Any], shortlist: list[dict[str, Any]]) -> Optional[str]:
    """Best-effort K.I.N. narrative via bridge dispatch. Returns None on any failure."""
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        candidate_lines = "\n".join(
            f"- {e.get('display_name', '?')} (dept={e.get('department', '?')}, "
            f"skill level={e.get('proficiency_level', '?')}, "
            f"model={e.get('primary_model', '?')})"
            for e in shortlist
        )
        prompt = (
            f"The capability '{gap['capability']}' is understaffed. "
            f"Reason: {gap['gap_reason']}.\n\n"
            f"Three decommissioned specialists are shortlisted:\n{candidate_lines}\n\n"
            "Write a concise 2-3 sentence rationale explaining why this gap matters "
            "and why these specific candidates are sensible picks. No preamble."
        )
        result = dispatch(
            capability="workforce_planning",
            prompt=prompt,
            prefer_agent="K.I.N.",
        )
        if result and getattr(result, "success", False):
            return (getattr(result, "response", "") or "").strip() or None
    except Exception as e:
        logger.info("K.I.N. narrative dispatch failed (non-fatal): %s", e)
    return None


def kin_generate_hire_proposals(max_proposals_per_run: int = MAX_PROPOSALS_PER_RUN):
    """Daily ~09:05 UTC. Generate hiring_candidates rows for understaffed capabilities.

    Flow per gap:
      1. SQL shortlist (top 3 decommissioned agents at Lv3+).
      2. Best-effort K.I.N. narrative via bridge dispatch.
      3. Insert via hiring_service.propose_for_gap (dedup handled there).
    """
    from services import hiring_service

    start = time.time()
    inserted = 0
    skipped_empty = 0
    skipped_dedup = 0

    try:
        gaps = _list_current_capability_gaps()
        for gap in gaps:
            if inserted >= max_proposals_per_run:
                break
            shortlist = hiring_service.get_shortlist(gap["capability"], limit=3)
            if not shortlist:
                skipped_empty += 1
                continue
            narrative = _generate_hire_narrative(gap, shortlist)
            row_id = hiring_service.propose_for_gap(
                capability=gap["capability"],
                gap_reason=gap["gap_reason"],
                shortlist=shortlist,
                narrative=narrative,
                proposed_by_agent_id=KIN_AGENT_ID,
            )
            if row_id is None:
                skipped_dedup += 1
            else:
                inserted += 1

        # Pool-saturation staffing tail BEFORE the summary log (#5187 defect 1):
        # this used to run AFTER _log_cycle, so its inserts were invisible in the
        # parent row — 2026-07-24 logged {"inserted": 0} on the exact run that
        # filed hiring_candidates 406-409. The tail keeps its own guard + its own
        # kin_recommend_pool_staffing log row; this belt-and-braces except only
        # protects the parent summary from a raise before that guard engages.
        pool_recommended = 0
        try:
            pool_recommended = kin_recommend_pool_staffing() or 0
        except Exception:
            logger.warning("pool staffing tail failed (zero-agent results unaffected)", exc_info=True)

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "kin_generate_hire_proposals",
            inserted + pool_recommended,
            0,
            duration_ms,
            details={
                "gaps_seen": len(gaps),
                "inserted": inserted,
                "inserted_pool_staffing": pool_recommended,
                # Post demand-gate this counts REAL demanded gaps with no
                # reactivation candidate — no longer 100% inventory noise.
                "skipped_empty_shortlist": skipped_empty,
                "skipped_dedup": skipped_dedup,
            },
        )
    except Exception as e:
        logger.exception("kin_generate_hire_proposals failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("kin_generate_hire_proposals", 0, 1, duration_ms, error_message=str(e))


def _emit_pool_staffing_alert(capability: str, gap: dict, row_id: int) -> None:
    """Best-effort C.R.E.E.D. accountability event + A.R.C.H.I.E. Telegram advisory for a
    NEW pool-saturation staffing recommendation. severity='info' — this is a TRANSPARENCY
    signal (the platform noticed its pool was maxed and recommended adding capacity), NOT a
    welfare violation, so it must not penalize the governance grade. Both paths are
    individually guarded: the hiring_candidates row is already persisted, so a comms hiccup
    must never lose the recommendation."""
    pool_size = gap.get("pool_size")
    backlog = gap.get("backlog")
    # The two signals must not borrow each other's words. A sole-agent gap has NO backlog
    # by design (a lone agent absorbs rather than queues), so the pool wording rendered
    # "all 1 active agent(s) ... with None dispatch(es) queued" and stamped the metadata
    # signal as pool_saturation — an alert that misdescribes its own cause.
    signal = gap.get("signal") or "pool_saturation"
    if signal == "sole_agent_saturation":
        msg = (
            f"K.I.N. flags '{capability}' as a single point of failure: its ONLY active agent "
            f"({gap.get('agent_name')}) is at/over its 24h token budget, so the dispatch throttle "
            "has no healthy peer to route to. A hiring recommendation "
            f"(candidate #{row_id}) is pending your approval in the DHQ Hiring Queue."
        )
    else:
        msg = (
            f"K.I.N. flags '{capability}' at capacity: all {pool_size} active agent(s) are at/over "
            f"their 24h token budget with {backlog} dispatch(es) queued in the last 24h. A hiring "
            f"recommendation (candidate #{row_id}) is pending your approval in the DHQ Hiring Queue."
        )
    try:
        from services import creed_emit

        creed_emit.emit_event(
            category="accountability",
            severity="info",
            description=msg,
            event_type="staffing_recommendation",
            agent_id=KIN_AGENT_ID,
            agent_name="K.I.N.",
            module="Welfare",
            metadata={
                "capability": capability,
                "pool_size": pool_size,
                "backlog": backlog,
                "hiring_candidate_id": row_id,
                "signal": signal,
            },
        )
    except Exception:
        logger.warning("pool-staffing CREED emit failed for %s", capability, exc_info=True)
    try:
        from services import telegram_service

        telegram_service.send_info("K.I.N. — staffing recommendation", msg)
    except Exception:
        logger.warning("pool-staffing Telegram advisory failed for %s", capability, exc_info=True)


def kin_recommend_pool_staffing():
    """Daily (tail of kin_generate_hire_proposals). Turn POOL-SATURATION staffing gaps — a
    whole skill-pool pinned at its 24h token-budget ceiling with a sustained dispatch
    backlog — into CREED-gated, human-approved hire recommendations.

    Never auto-hires: inserts a PENDING hiring_candidates row (approved via the DHQ Hiring
    Queue / Telegram) and emits a C.R.E.E.D. accountability event + A.R.C.H.I.E. Telegram
    advisory. Dedup (one pending row per capability) is handled by propose_for_gap. Fully
    guarded — a failure here must not affect the zero-agent proposals that ran before it."""
    from services import hiring_service, welfare_governance_service

    start = time.time()
    recommended = 0
    gaps = []
    try:
        gaps = welfare_governance_service.recommend_pool_staffing_gaps()
        for gap in gaps:
            cap = gap["capability"]
            shortlist = hiring_service.get_shortlist(cap, limit=3)
            if not shortlist:
                # Capacity gap with no decommissioned specialist to reactivate → recommend a
                # NET-NEW hire. propose_for_gap skips an empty shortlist, so seed one entry.
                shortlist = [
                    {
                        "type": "new_hire",
                        "capability": cap,
                        "note": "no decommissioned specialist available — recommend a net-new agent",
                    }
                ]
            narrative = (
                f"Entire active pool for '{cap}' ({gap['pool_size']} agent(s)) is at/over its 24h "
                f"token budget with {gap['backlog']} dispatch(es) queued in the last 24h — the pool is "
                "at capacity. Recommend adding an agent so work isn't throttled and welfare budgets "
                "aren't breached."
            )
            row_id = hiring_service.propose_for_gap(
                capability=cap,
                gap_reason=gap["gap_reason"],
                shortlist=shortlist,
                narrative=narrative,
                proposed_by_agent_id=KIN_AGENT_ID,
            )
            if row_id is None:
                continue  # dedup — a pending recommendation for this capability already exists
            recommended += 1
            _emit_pool_staffing_alert(cap, gap, row_id)

        # SOLE-AGENT saturation (2026-08-02). recommend() has described this case since
        # #4090, but only as advisory text — this loop is the only path to the DHQ Hiring
        # Queue, and it required a pool of >= 2, so a lone maxed agent was never queued for
        # hire. Runs AFTER the pool loop and is independently guarded: a failure here must
        # not lose the pool recommendations already filed above.
        try:
            solo_gaps = welfare_governance_service.recommend_sole_agent_staffing_gaps()
        except Exception:  # noqa: BLE001
            logger.warning("sole-agent staffing gap scan failed", exc_info=True)
            solo_gaps = []

        for gap in solo_gaps:
            cap = gap["capability"]
            shortlist = hiring_service.get_shortlist(cap, limit=3)
            if not shortlist:
                shortlist = [
                    {
                        "type": "new_hire",
                        "capability": cap,
                        "note": "no decommissioned specialist available — recommend a net-new agent",
                    }
                ]
            narrative = (
                f"'{cap}' is served by exactly ONE active agent ({gap['agent_name']}), and that "
                "agent is at/over its 24h token budget. This is a single point of failure as well "
                "as a capacity gap: the dispatch throttle has no healthy peer to route to, so work "
                "either waits or falls back to the exhausted agent, and any rest cycle or node "
                "outage stops the capability entirely. Note there is deliberately NO backlog "
                "requirement here — a lone agent has nothing to queue behind and absorbs the load "
                "instead, so an empty dispatch queue is a symptom of the overwork, not evidence "
                "against it. Recommend reactivating a bench specialist or adding an agent."
            )
            row_id = hiring_service.propose_for_gap(
                capability=cap,
                gap_reason=gap["gap_reason"],
                shortlist=shortlist,
                narrative=narrative,
                proposed_by_agent_id=KIN_AGENT_ID,
            )
            if row_id is None:
                continue  # dedup — pool loop or an earlier run already filed this capability
            recommended += 1
            _emit_pool_staffing_alert(cap, gap, row_id)

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "kin_recommend_pool_staffing",
            recommended,
            0,
            duration_ms,
            details={
                "gaps_seen": len(gaps),
                "sole_agent_gaps_seen": len(solo_gaps),
                "recommended": recommended,
            },
        )
    except Exception as e:
        logger.exception("kin_recommend_pool_staffing failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("kin_recommend_pool_staffing", 0, 1, duration_ms, error_message=str(e))
    return recommended


def expire_stale_hire_proposals():
    """Daily 04:30 UTC. Flip pending hiring_candidates > 14d old to 'expired'."""
    from services import hiring_service

    start = time.time()
    try:
        n = hiring_service.expire_stale_proposals(max_age_days=14)
        _log_cycle(
            "expire_stale_hire_proposals",
            n,
            0,
            int((time.time() - start) * 1000),
            details={"expired": n},
        )
    except Exception as e:
        logger.exception("expire_stale_hire_proposals failed")
        _log_cycle(
            "expire_stale_hire_proposals",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


# ---------------------------------------------------------------------------
# Approval queue hygiene
# ---------------------------------------------------------------------------


def reap_stale_pending_approvals(max_age_days: int = 7):
    """Auto-cancel bridge_jobs stuck in pending_approval past the age cap.

    Jobs that never get approved/denied hold an agent's in-flight
    budget slot indefinitely. Pixel was carrying 5 month-old cloud
    image-gen approvals when this session audited the roster; they
    legitimately counted as active work under the canonical definition
    but the approvals themselves were abandoned. This reaper moves
    those jobs to 'cancelled' (same path as manual deny), which frees
    the counter via the existing complete_job decrement.

    Runs daily. Returns dict with counts reaped + affected agents.
    """
    from db import get_db

    start = time.time()
    reaped = 0
    affected: dict = {}

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE bridge_jobs
            SET status = 'cancelled',
                completed_at = NOW(),
                updated_at = NOW(),
                error_message = COALESCE(error_message, '') ||
                    CASE WHEN COALESCE(error_message, '') = '' THEN '' ELSE '; ' END ||
                    'auto-reaped: pending_approval > ' || %s || 'd'
            WHERE status = 'pending_approval'
              AND created_at < NOW() - (%s || ' days')::INTERVAL
            RETURNING id, agent_name
            """,
            (max_age_days, max_age_days),
        )
        rows = cur.fetchall()
        reaped = len(rows)
        for r in rows:
            name = r[1] if r and len(r) > 1 else None
            if name:
                affected[name] = affected.get(name, 0) + 1

        # Decrement each affected agent's budget counter to match the
        # cancelled jobs (complete_job's decrement path doesn't fire here
        # because we UPDATE'd directly, not called complete_job per job).
        for name, count in affected.items():
            cur.execute(
                """
                UPDATE agent_budgets ab
                SET current_task_count = GREATEST(0, COALESCE(current_task_count, 0) - %s),
                    updated_at = NOW()
                FROM agents a
                WHERE a.id = ab.agent_id AND a.name = %s
                """,
                (count, name),
            )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.exception("reap_stale_pending_approvals failed")
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("reap_stale_pending_approvals", 0, 1, duration_ms, error_message=str(exc))
        return {"reaped": 0, "affected": {}, "error": str(exc)}

    if reaped:
        logger.info(
            "reap_stale_pending_approvals: reaped %d stale pending_approval job(s) across %d agent(s): %s",
            reaped,
            len(affected),
            affected,
        )

    duration_ms = int((time.time() - start) * 1000)
    _log_cycle(
        "reap_stale_pending_approvals",
        reaped,
        0,
        duration_ms,
        details={"reaped": reaped, "affected_agents": affected, "max_age_days": max_age_days},
    )
    return {"reaped": reaped, "affected": affected}


# ---------------------------------------------------------------------------
# Approval queue — resume approved bridge jobs
# ---------------------------------------------------------------------------


def _resume_image_generation(row, external_providers):
    """Execute a claimed 'approved'-status image_generation bridge_job.

    Returns:
        (final_status, extras) where:
          final_status is 'completed' or 'failed'
          extras has keys: file_path, cost_usd, provider_key, user_id (or error)
    """
    import json as _json

    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = _json.loads(metadata)
        except Exception:
            metadata = {}

    prompt = metadata.get("prompt", "")
    user_id = metadata.get("user_id")
    params = metadata.get("image_params") or {}

    providers = [
        p for p in external_providers.get_providers_with_capability("image_gen") if (p.get("tier_position") or 0) >= 5
    ]
    if not providers:
        return ("failed", {"error": "no paid image providers available"})
    provider = providers[0]
    result = external_providers.generate_media(
        provider["provider_key"],
        {"type": "image", "prompt": prompt, "params": params},
    )
    if result and result.get("success"):
        return (
            "completed",
            {
                "file_path": result.get("file_path", ""),
                "cost_usd": float(result.get("cost_usd") or 0),
                "provider_key": provider["provider_key"],
                "user_id": user_id,
            },
        )
    err = (result.get("error") if result else "generate_media returned falsy") or "unknown error"
    return ("failed", {"error": str(err)})


# Dispatch table: job_type → handler function.
# To support a new job_type, add one entry here + implement the handler above.
_BRIDGE_RESUME_HANDLERS = {
    "image_generation": _resume_image_generation,
}


def resume_approved_bridge_jobs():
    """Re-dispatch bridge_jobs rows approved via the web Approvals UI.

    Selects rows where status='approved' AND job_type IN registered handlers.
    Atomically claims each (approved → running), then calls the matching
    handler. Applies the handler's (final_status, extras) to the DB.
    """
    from db import get_db

    start = time.time()

    registered_types = list(_BRIDGE_RESUME_HANDLERS.keys())
    if not registered_types:
        return 0

    # Fetch up to 10 approved rows for registered job_types (oldest first).
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, job_type, metadata, agent_name
               FROM bridge_jobs
               WHERE status = 'approved' AND job_type = ANY(%s)
               ORDER BY approved_at NULLS LAST, id
               LIMIT 10""",
            (registered_types,),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not rows:
        return 0

    try:
        from ai_bridge import external_providers
    except Exception as e:
        logger.error("resume_approved_bridge_jobs: external_providers unavailable: %s", e)
        return 0

    processed = 0
    for row in rows:
        # Support both tuple rows (plain cursor) and dict rows (RealDictCursor).
        if isinstance(row, dict):
            job_id = row["id"]
            job_type = row["job_type"]
        else:
            job_id = row[0]
            job_type = row[1]
            row = {"id": row[0], "job_type": row[1], "metadata": row[2], "agent_name": row[3]}

        handler = _BRIDGE_RESUME_HANDLERS.get(job_type)
        if handler is None:
            continue

        # Atomically claim: flip approved → running. Skip if another worker beat us.
        claim_conn = get_db()
        claim_cur = claim_conn.cursor()
        try:
            claim_cur.execute(
                """UPDATE bridge_jobs
                   SET status = 'running', updated_at = NOW()
                   WHERE id = %s AND status = 'approved'""",
                (job_id,),
            )
            claim_conn.commit()
            if claim_cur.rowcount == 0:
                continue  # already claimed by another worker
        finally:
            claim_cur.close()
            claim_conn.close()

        try:
            final_status, extras = handler(row, external_providers)
        except Exception as exc:
            logger.warning("resume_approved_bridge_jobs: handler for %s raised: %s", job_type, exc)
            final_status, extras = ("failed", {"error": str(exc)})

        if final_status == "completed":
            file_path = extras.get("file_path", "")
            done_conn = get_db()
            done_cur = done_conn.cursor()
            try:
                done_cur.execute(
                    """UPDATE bridge_jobs
                       SET status = 'completed',
                           description = COALESCE(description, '') || ' [cloud: ' || %s || ']',
                           completed_steps = total_steps,
                           completed_at = NOW(),
                           updated_at = NOW()
                       WHERE id = %s""",
                    (file_path, job_id),
                )
                done_conn.commit()
            finally:
                done_cur.close()
                done_conn.close()
            # Log cloud usage for cost tracking.
            try:
                cost = float(extras.get("cost_usd") or 0)
                provider_key = extras.get("provider_key")
                user_id = extras.get("user_id")
                if provider_key:
                    usage_conn = get_db()
                    usage_cur = usage_conn.cursor()
                    try:
                        usage_cur.execute(
                            """INSERT INTO cloud_model_usage
                               (model_name, provider, prompt_tokens, completion_tokens,
                                cost_usd, user_id, task_type, success)
                               VALUES (%s, %s, 0, 0, %s, %s, %s, TRUE)""",
                            (
                                f"{provider_key}_image",
                                provider_key,
                                cost,
                                user_id,
                                job_type,
                            ),
                        )
                        usage_conn.commit()
                    finally:
                        usage_cur.close()
                        usage_conn.close()
            except Exception as log_err:
                logger.debug("resume_approved_bridge_jobs: cloud_model_usage log failed: %s", log_err)
            processed += 1
            logger.info(
                "resume_approved_bridge_jobs: job %d completed via %s → %s",
                job_id,
                extras.get("provider_key", "?"),
                file_path,
            )
        else:
            err = extras.get("error", "unknown error")
            fail_conn = get_db()
            fail_cur = fail_conn.cursor()
            try:
                fail_cur.execute(
                    """UPDATE bridge_jobs
                       SET status = 'failed',
                           error_message = %s,
                           updated_at = NOW()
                       WHERE id = %s""",
                    (str(err)[:500], job_id),
                )
                fail_conn.commit()
            finally:
                fail_cur.close()
                fail_conn.close()
            logger.warning("resume_approved_bridge_jobs: job %d failed: %s", job_id, err)

    duration_ms = int((time.time() - start) * 1000)
    _log_cycle(
        "resume_approved_bridge_jobs",
        processed,
        0,
        duration_ms,
        details={"processed": processed},
    )
    return processed


def refresh_website_directory():
    """Regenerate directory-fallback.json and push it to Hostinger via API.

    Runs every 6 hours so the static fallback always reflects the live roster.
    Also uploads just the JSON file via TUS (no full-site redeploy needed).
    """
    import json
    import os
    import threading

    import requests

    try:
        # Fetch live public roster from the platform itself
        resp = requests.get(
            "http://127.0.0.1:3000/api/public/directory",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("refresh_website_directory: failed to fetch roster: %s", exc)
        return

    agents = data.get("agents", data) if isinstance(data, dict) else data

    _site_data = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "website",
            "kytranempowerment.com",
            "data",
        )
    )
    fallback_path = os.path.join(_site_data, "directory-fallback.json")
    directors_path = os.path.join(_site_data, "directors.json")

    # Write directory-fallback.json (all public agents)
    try:
        with open(fallback_path, "w") as fh:
            json.dump({"agents": agents}, fh, indent=2, default=str)
        logger.info("refresh_website_directory: wrote %d agents to fallback JSON", len(agents))
    except Exception as exc:
        logger.warning("refresh_website_directory: failed to write fallback: %s", exc)
        return

    # Write directors.json (is_director subset — used by ai-directors.html fallback)
    directors = [a for a in agents if a.get("is_director")]
    if not directors:
        directors = [a for a in agents if a.get("acronym")]
    try:
        with open(directors_path, "w") as fh:
            json.dump({"agents": directors}, fh, indent=2, default=str)
        logger.info("refresh_website_directory: wrote %d directors to directors.json", len(directors))
    except Exception as exc:
        logger.warning("refresh_website_directory: failed to write directors.json: %s", exc)

    # Push the JSON file to Hostinger via TUS in a background thread
    api_key = os.getenv("HOSTINGER_API_KEY", "")
    if not api_key:
        logger.debug("refresh_website_directory: HOSTINGER_API_KEY not set, skipping push")
        return

    def _push():
        try:
            base = "https://developers.hostinger.com"
            auth = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

            r = requests.get(
                f"{base}/api/hosting/v1/websites?domain=kytranempowerment.com",
                headers=auth,
                timeout=10,
            )
            r.raise_for_status()
            username = r.json()["data"][0]["username"]

            r = requests.post(
                f"{base}/api/hosting/v1/files/upload-urls",
                headers=auth,
                json={"username": username, "domain": "kytranempowerment.com"},
                timeout=10,
            )
            r.raise_for_status()
            creds = r.json()
            upload_url = creds["url"].rstrip("/")
            auth_token = creds["auth_key"]
            auth_rest = creds["rest_auth_key"]

            file_size = os.path.getsize(fallback_path)
            endpoint = f"{upload_url}/data/directory-fallback.json?override=true"
            tus_h = {
                "X-Auth": auth_token,
                "X-Auth-Rest": auth_rest,
                "upload-length": str(file_size),
                "upload-offset": "0",
            }
            r = requests.post(endpoint, data=b"", headers=tus_h, timeout=30)
            if r.status_code != 201:
                logger.warning("directory fallback TUS init failed: %s", r.status_code)
                return
            with open(fallback_path, "rb") as fh:
                r = requests.patch(
                    endpoint,
                    data=fh,
                    headers={**tus_h, "Content-Type": "application/offset+octet-stream"},
                    timeout=60,
                )
            if r.status_code in (200, 204):
                logger.info("refresh_website_directory: fallback JSON pushed to Hostinger")
            else:
                logger.warning("directory fallback PATCH failed: %s", r.status_code)

            # Also push directors.json (ai-directors.html fallback)
            def _tus_upload(local_path, remote_rel):
                r2 = requests.get(
                    f"{base}/api/hosting/v1/files/upload-urls",
                    headers=auth,
                    timeout=10,
                )
                r2.raise_for_status()
                c2 = r2.json() if r2.status_code == 200 else None
                if not c2:
                    c2 = {"url": upload_url, "auth_key": auth_token, "rest_auth_key": auth_rest}
                ep = f"{c2['url'].rstrip('/')}/{remote_rel}?override=true"
                fsize = os.path.getsize(local_path)
                h2 = {
                    "X-Auth": c2["auth_key"],
                    "X-Auth-Rest": c2["rest_auth_key"],
                    "upload-length": str(fsize),
                    "upload-offset": "0",
                }
                if requests.post(ep, data=b"", headers=h2, timeout=30).status_code != 201:
                    return
                with open(local_path, "rb") as f2:
                    requests.patch(
                        ep,
                        data=f2,
                        headers={**h2, "Content-Type": "application/offset+octet-stream"},
                        timeout=60,
                    )

            _tus_upload(directors_path, "data/directors.json")
            logger.info("refresh_website_directory: directors.json pushed to Hostinger")

        except Exception as exc:
            logger.warning("refresh_website_directory push error: %s", exc)

    threading.Thread(target=_push, daemon=True, name="dir-fallback-push").start()


def signal_linkedin_draft(account_filter="all"):
    """S.I.G.N.A.L. drafts a LinkedIn post and queues it for Telegram approval.

    Runs Tue + Thu at 09:00 local time. S.I.G.N.A.L. generates content based
    on recent platform activity and the hashtag rotation pool. The draft goes
    into the Tier-2 approval queue — Kytran approves/denies via Telegram.
    On approval, agent_loop executes linkedin_post via browser_service.
    """
    import sys

    sys.path.insert(0, "/app")

    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # ── 1. Pick hashtags from rotation pool ───────────────────────────────
        # Select 4-5 hashtags: mix of high-engagement + not used in 7 days
        cur.execute(
            """
            SELECT hashtag FROM linkedin_hashtag_stats
            WHERE last_used IS NULL OR last_used < NOW() - INTERVAL '7 days'
            ORDER BY avg_engagement DESC, RANDOM()
            LIMIT 5
            """
        )
        hashtags = [r["hashtag"] for r in cur.fetchall()]
        if not hashtags:
            # Fallback: any hashtags
            cur.execute("SELECT hashtag FROM linkedin_hashtag_stats ORDER BY RANDOM() LIMIT 5")
            hashtags = [r["hashtag"] for r in cur.fetchall()]

        # ── 2. Get context for S.I.G.N.A.L. ─────────────────────────────────
        # Recent commits for "building in public" content
        recent_context = ""
        try:
            import subprocess

            r = subprocess.run(
                ["git", "log", "--oneline", "-5", "--format=%s"],
                cwd="/mnt/archie_brain",
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                recent_context = r.stdout.strip()
        except Exception:
            pass

        cur.close()
        conn.close()

        # ── 3. Dispatch to S.I.G.N.A.L. for content generation ───────────────

        # Day-of-week content theme — resolved from per-account DB calendar
        from datetime import datetime as _dt

        weekday = _dt.now().weekday()  # 0=Mon … 6=Sun
        _lookup_account = account_filter if account_filter not in ("all", None) else "personal"
        theme_name = "Content Update"
        theme_guidance = "Share a recent platform milestone or AI ethics insight relevant to this brand."
        try:
            from database import get_db_cursor as _gc_theme

            with _gc_theme() as (_c_t, _cur_t):
                _cur_t.execute(
                    """
                    SELECT sct.name, sct.tone
                    FROM social_content_calendar scc
                    JOIN social_content_themes sct ON sct.id = scc.theme_id
                    WHERE scc.account = %s AND scc.day_of_week = %s AND scc.is_active = TRUE
                    ORDER BY scc.slot_order
                    LIMIT 1
                    """,
                    (_lookup_account, weekday),
                )
                _theme_row = _cur_t.fetchone()
                if _theme_row:
                    theme_name = _theme_row["name"]
                    theme_guidance = _theme_row["tone"] or theme_guidance
        except Exception as _te:
            logger.warning("[LinkedInDraft] DB theme lookup failed: %s", _te)

        # Fetch S.I.G.N.A.L.'s style guide from KB (denial learnings)
        style_notes = ""
        try:
            from tools.consciousness.services.knowledge_service import search_knowledge

            _sk = search_knowledge(
                search="linkedin style guide denied draft avoid",
                category="signal_style_guide",
                limit=3,
            )
            style_entries = (_sk or {}).get("entries", [])
            if style_entries:
                style_notes = "\n\nStyle guide (avoid these patterns):\n" + "\n".join(
                    f"- {(e.get('snippet') or e.get('content') or '')[:150]}" for e in style_entries
                )
        except Exception:
            pass

        # A.R.C.H.I.E. context — recent milestones, tasks, decisions
        archie_context = ""
        try:
            from database import get_db_cursor as _gc

            with _gc() as (_cc, _acur):
                # Completed tasks in last 7 days
                _acur.execute(
                    """SELECT title FROM unified_tasks
                       WHERE status = 'completed' AND updated_at > NOW() - INTERVAL '7 days'
                       ORDER BY updated_at DESC LIMIT 5"""
                )
                done_tasks = [r["title"] for r in _acur.fetchall()]

                # Recent decisions
                _acur.execute(
                    """SELECT decision FROM project_decisions
                       ORDER BY created_at DESC LIMIT 3"""
                )
                decisions = [r["decision"][:80] for r in _acur.fetchall()]

            parts = []
            if done_tasks:
                parts.append("Recent wins: " + "; ".join(done_tasks[:3]))
            if decisions:
                parts.append("Recent decisions: " + "; ".join(decisions[:2]))
            archie_context = "\n".join(parts)
        except Exception:
            pass

        # Personal check-in section — skipped when account_filter='company' or 'creed'
        # (those accounts have no personal check-in step; they draft directly).
        goto_company = account_filter in ("company", "creed")
        if not goto_company:
            import json as _json
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td

            checkin_state = {
                "archie_context": archie_context,
                "recent_context": recent_context,
                "hashtags": hashtags,
                "theme_name": theme_name,
                "theme_guidance": theme_guidance,
                "style_notes": style_notes,
                "expires_at": (_dt.now(_tz.utc) + _td(hours=4)).isoformat(),
                "status": "pending",
            }
            try:
                from database import get_db_cursor as _gc2

                with _gc2(commit=True) as (_cc2, _sc):
                    _sc.execute(
                        """INSERT INTO system_config (key, value, updated_at)
                           VALUES ('signal_personal_checkin', %s, NOW())
                           ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
                        (_json.dumps(checkin_state), _json.dumps(checkin_state)),
                    )
            except Exception as _se:
                logger.warning("[LinkedInDraft] Could not store checkin state: %s", _se)

            # Send Telegram check-in
            try:
                from services.director_report_service import submit_via_inbox

                briefing_lines = []
                if archie_context:
                    briefing_lines.append(archie_context)
                if recent_context:
                    briefing_lines.append(f"Git: {recent_context[:200]}")

                briefing = "\n".join(briefing_lines) or "Nothing new captured yet."
                checkin_msg = (
                    f"A.R.C.H.I.E. briefing for your personal post ({theme_name}):\n\n"
                    f"{briefing}\n\n"
                    f"What do you want to share today? "
                    f"Reply to this and I'll use your words in the post. "
                    f"(4h window — if no reply, I'll draft from the briefing above)"
                )
                submit_via_inbox(
                    category="signal_checkin",
                    title="S.I.G.N.A.L. Check-In",
                    message=checkin_msg,
                    source_agent="A.R.C.H.I.E.",
                    # Routine content-calendar check-in ("what do you want to post?"), NOT a
                    # system incident — keep it out of the cockpit's red `critical` state.
                    # 'medium' surfaces it in the bell without flashing the header red.
                    severity="medium",
                    department="Executive Office",
                )
                logger.info("[LinkedInDraft] Personal check-in sent via Telegram")
            except Exception as _te:
                logger.warning("[LinkedInDraft] Telegram check-in failed: %s", _te)

            logger.info("[LinkedInDraft] Personal check-in pending. Company posts will follow.")
            goto_company = True

        # goto_company=True means check-in was sent — skip personal draft/approval.
        # Personal post will be triggered by Telegram reply or the timeout job.
        selected_hashtags = hashtags[:3]
        approval_id = None

        if not goto_company:
            # Direct path (future: used when check-in reply already received)
            pass

        if approval_id:
            logger.info("[LinkedInDraft] Personal draft queued (id=%s)", approval_id)
        else:
            logger.info("[LinkedInDraft] Personal post deferred — check-in sent, awaiting Kytran's reply")

        # Queue company post ~3h later (staggered — don't flood Telegram)
        import threading

        _ann_context = recent_context
        _hashtags_copy = list(selected_hashtags)
        _theme = f"{theme_name}: {theme_guidance}"
        _style = style_notes

        # Skip company section when running personal-only
        if account_filter == "personal":
            logger.info("[LinkedInDraft] personal-only run — skipping company posts")
            return

        # Creed-only path: draft EN + FR posts for the C.R.E.E.D. Institute org page.
        # Mirrors the company EN+FR cadence (30 min apart) but routes to a separate
        # post_type so the autonomy worker dispatches to linkedin_creed_post skill.
        if account_filter == "creed":
            _CREED_STAGGER_SECS = 30 * 60  # 30 minutes between EN and FR

            def _queue_creed_single(lang, delay_secs=0):
                def _run():
                    if delay_secs:
                        import time as _t

                        _t.sleep(delay_secs)
                    try:
                        from signal_dispatch import _draft_and_queue

                        system = None
                        try:
                            from database import get_db_cursor

                            with get_db_cursor() as (_c, _cur):
                                _cur.execute(
                                    "SELECT system_prompt FROM agents WHERE name = %s",
                                    ("S.I.G.N.A.L.",),
                                )
                                _row = _cur.fetchone()
                                if _row and _row.get("system_prompt"):
                                    system = _row["system_prompt"]
                        except Exception:
                            pass

                        announcement = (
                            "Weekly C.R.E.E.D. Institute post on AI ethics, governance, "
                            f"or accountability. Theme: {_theme}. Recent platform context: {_ann_context}"
                        )
                        aid, _ = _draft_and_queue(
                            announcement, "creed", "professional", _hashtags_copy, 5, system, language_only=lang
                        )
                        if aid == -1:
                            logger.info(
                                "[LinkedInDraft] Creed %s draft deferred — model cold, callback registered",
                                lang.upper(),
                            )
                        else:
                            logger.info("[LinkedInDraft] Creed %s draft queued (id=%s)", lang.upper(), aid)
                    except Exception as _e:
                        logger.error("[LinkedInDraft] Creed %s draft failed: %s", lang.upper(), _e)

                return _run

            t1 = threading.Thread(target=_queue_creed_single("en", delay_secs=10), daemon=True)
            t1.start()
            t2 = threading.Thread(target=_queue_creed_single("fr", delay_secs=_CREED_STAGGER_SECS), daemon=True)
            t2.start()
            logger.info("[LinkedInDraft] Creed posts scheduled: EN first, FR 30 min later")

            duration_ms = int((time.time() - start) * 1000)
            _log_cycle(
                "signal_linkedin_draft",
                1,
                0,
                duration_ms,
                {"account": "creed", "hashtags": selected_hashtags},
            )
            return

        # Company posts: EN + FR as separate posts, 30 min apart.
        # Rotation tracked in system_config so they alternate each cycle.
        _COMPANY_STAGGER_SECS = 30 * 60  # 30 minutes between EN and FR

        def _get_and_toggle_rotation():
            """Return ('en', 'fr') or ('fr', 'en') and flip for next cycle."""
            try:
                from database import get_db_cursor

                with get_db_cursor(commit=True) as (_c, _cur):
                    _cur.execute("SELECT value FROM system_config WHERE key = 'signal_company_rotation'")
                    _row = _cur.fetchone()
                    current = _row["value"] if _row else "en_first"
                    next_val = "fr_first" if current == "en_first" else "en_first"
                    _cur.execute(
                        """INSERT INTO system_config (key, value, updated_at)
                           VALUES ('signal_company_rotation', %s, NOW())
                           ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
                        (next_val, next_val),
                    )
                return ("en", "fr") if current == "en_first" else ("fr", "en")
            except Exception:
                return ("en", "fr")

        first_lang, second_lang = _get_and_toggle_rotation()

        def _queue_company_single(lang, delay_secs=0):
            def _run():
                if delay_secs:
                    import time as _t

                    _t.sleep(delay_secs)
                try:
                    from signal_dispatch import _draft_and_queue

                    system = None
                    try:
                        from database import get_db_cursor

                        with get_db_cursor() as (_c, _cur):
                            _cur.execute(
                                "SELECT system_prompt FROM agents WHERE name = %s",
                                ("S.I.G.N.A.L.",),
                            )
                            _row = _cur.fetchone()
                            if _row and _row.get("system_prompt"):
                                system = _row["system_prompt"]
                    except Exception:
                        pass

                    announcement = f"Theme: {_theme}\nRecent platform activity: {_ann_context}"
                    aid, _ = _draft_and_queue(
                        announcement, "company", "professional", _hashtags_copy, 5, system, language_only=lang
                    )
                    if aid == -1:
                        logger.info(
                            "[LinkedInDraft] Company %s draft deferred — model cold, callback registered", lang.upper()
                        )
                    else:
                        logger.info("[LinkedInDraft] Company %s draft queued (id=%s)", lang.upper(), aid)
                except Exception as _e:
                    logger.error("[LinkedInDraft] Company %s draft failed: %s", lang.upper(), _e)

            return _run

        # First language: slight delay (10s) so personal clears first
        t1 = threading.Thread(target=_queue_company_single(first_lang, delay_secs=10), daemon=True)
        t1.start()
        # Second language: 30 min later
        t2 = threading.Thread(target=_queue_company_single(second_lang, delay_secs=_COMPANY_STAGGER_SECS), daemon=True)
        t2.start()
        logger.info(
            "[LinkedInDraft] Company posts scheduled: %s first, %s second (30 min later)",
            first_lang.upper(),
            second_lang.upper(),
        )

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "signal_linkedin_draft", 1, 0, duration_ms, {"approval_id": approval_id, "hashtags": selected_hashtags}
        )

    except Exception as exc:
        logger.error("[LinkedInDraft] Failed: %s", exc)
        _log_cycle("signal_linkedin_draft", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])


def signal_linkedin_analytics():
    """Fetch LinkedIn analytics and update hashtag engagement stats.

    Runs every 6 hours. Checks linkedin_post_log for posts where analytics
    haven't been fetched yet, grabs current profile metrics via browser_service,
    and updates hashtag_stats with engagement correlations.
    Scheduled: every 6 hours.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    try:
        from services.browser_service import run_skill_sync

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get posts older than 20h without analytics
        cur.execute(
            """
            SELECT id, hashtags, posted_at FROM linkedin_post_log
            WHERE analytics_fetched_at IS NULL
              AND posted_at < NOW() - INTERVAL '20 hours'
              AND status = 'posted'
            ORDER BY posted_at DESC
            LIMIT 5
            """
        )
        pending = cur.fetchall()

        if not pending:
            cur.close()
            conn.close()
            _log_cycle("signal_linkedin_analytics", 0, 0, int((time.time() - start) * 1000))
            return

        # Fetch current analytics snapshot
        result = run_skill_sync("linkedin_analytics", {"mode": "profile"}, timeout_s=90)
        analytics = result.get("analytics", {})

        updated = 0
        for post in pending:
            # Mark analytics as fetched even if we can't get per-post stats
            cur.execute(
                """UPDATE linkedin_post_log
                   SET analytics_fetched_at = NOW()
                   WHERE id = %s""",
                (post["id"],),
            )
            # Update hashtag stats — mark as used and bump usage count
            for tag in post["hashtags"] or []:
                cur.execute(
                    """INSERT INTO linkedin_hashtag_stats (hashtag, usage_count, last_used, updated_at)
                       VALUES (%s, 1, %s, NOW())
                       ON CONFLICT (hashtag) DO UPDATE SET
                           usage_count = linkedin_hashtag_stats.usage_count + 1,
                           last_used   = EXCLUDED.last_used,
                           updated_at  = NOW()""",
                    (tag, post["posted_at"]),
                )
            updated += 1

        conn.commit()
        cur.close()
        conn.close()
        logger.info("[LinkedInAnalytics] Updated %d posts, analytics=%s", updated, analytics)
        _log_cycle("signal_linkedin_analytics", updated, 0, int((time.time() - start) * 1000))

    except Exception as exc:
        logger.error("[LinkedInAnalytics] Failed: %s", exc)
        _log_cycle("signal_linkedin_analytics", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])


def _dispatch_social_post_draft(prompt: str, prefer_agent: str = "S.I.G.N.A.L.", **kwargs):
    """Dispatch a social_post_draft capability call with one retry on Ollama 500 errors.

    Ollama HTTP 500 during inference means the model failed to load mid-generation
    (VRAM eviction or OOM). A single retry after a brief pause recovers ~70% of
    these cases without cascading to cloud escalation.

    Returns the DispatchResult (may have success=False if both attempts fail or
    queued=True if the model is cold and the task was deferred).
    """
    import time as _time

    from tools.department_hq.services.department_dispatcher import dispatch

    result = dispatch(
        capability="social_post_draft",
        prompt=prompt,
        prefer_agent=prefer_agent,
        **kwargs,
    )

    # Retry once on Ollama 500 — model may have been evicted mid-inference.
    # queued=True means the dispatcher already handled it; don't retry those.
    if (
        result is not None
        and not getattr(result, "queued", False)
        and not result.success
        and "500" in str(getattr(result, "error", "") or "")
    ):
        logger.warning(
            "[SignalDispatch] Ollama 500 on social_post_draft — retrying in 5s (prefer_agent=%s)",
            prefer_agent,
        )
        _time.sleep(5)
        result = dispatch(
            capability="social_post_draft",
            prompt=prompt,
            prefer_agent=prefer_agent,
            **kwargs,
        )

    # Cold boot: model not loaded yet. Mark as queued so callers skip gracefully
    # rather than logging a failure. The job will retry on the next scheduled cycle.
    if result is not None and not result.success and not getattr(result, "queued", False):
        _err = str(getattr(result, "error", "") or "")
        if "cold boot" in _err or "not ready" in _err:
            logger.info(
                "[SignalDispatch] social_post_draft cold boot — deferring to next cycle (prefer_agent=%s)",
                prefer_agent,
            )
            result.queued = True

    return result


def signal_notification_monitor():
    """Check LinkedIn notifications and queue replies to comments for Telegram approval.

    Runs every morning at 08:00. S.I.G.N.A.L. reads notifications, identifies
    comments/mentions that need a response, drafts replies, and queues them
    as Tier-2 approvals. Kytran approves/edits via Telegram before sending.
    """
    from services.browser_service import run_skill_sync

    start = time.time()
    try:
        # 1. Fetch notifications
        result = run_skill_sync("linkedin_notifications", {"limit": 20, "unread_only": True}, timeout_s=90)
        notifications = result.get("notifications", [])
        comments = [n for n in notifications if n.get("type") in ("comment", "mention", "reply")]

        if not comments:
            logger.info("[NotifMonitor] No comments/mentions to respond to")
            _log_cycle("signal_notification_monitor", 0, 0, int((time.time() - start) * 1000))
            return

        queued = 0
        try:
            from ai_bridge.agent_loop import request_approval
        except ImportError:
            return

        for notif in comments[:5]:  # max 5 replies per run
            text = notif.get("text", "")[:300]
            link = notif.get("link", "")
            if not text or not link:
                continue

            # S.I.G.N.A.L. drafts a reply (retry on Ollama 500)
            draft_result = _dispatch_social_post_draft(
                prompt=(
                    f"Draft a short LinkedIn reply to this notification:\n{text}\n\n"
                    "Reply as Kytran — professional, friendly, genuine. "
                    "Under 80 words. No hashtags."
                ),
            )
            reply_text = (draft_result.response or "").strip() if draft_result and draft_result.success else ""
            if not reply_text:
                continue

            request_approval(
                action_type="linkedin_reply",
                action_data={"reply_to": link, "message": reply_text, "browser_agent_id": 342},
                reason=f"S.I.G.N.A.L. reply draft:\nContext: {text[:150]}\nDraft: {reply_text}",
                tier=2,
                requested_by="S.I.G.N.A.L.",
                priority=4,
            )
            queued += 1

        logger.info("[NotifMonitor] Queued %d reply approvals", queued)
        _log_cycle("signal_notification_monitor", queued, 0, int((time.time() - start) * 1000))

    except Exception as exc:
        logger.error("[NotifMonitor] Failed: %s", exc)
        _log_cycle("signal_notification_monitor", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])


def _draft_personal_post_from_context(kytran_reply: str, state: dict) -> None:
    """Generate Kytran's personal LinkedIn post from check-in reply + A.R.C.H.I.E. context.

    Called by the Telegram reply handler OR the timeout job.
    Produces a short bilingual (EN + ⚜️ FR) human post and queues for approval.
    """
    import sys

    sys.path.insert(0, "/app")

    archie_context = state.get("archie_context", "")
    recent_context = state.get("recent_context", "")
    hashtags = state.get("hashtags", [])
    theme_name = state.get("theme_name", "Building in Public")
    theme_guidance = state.get("theme_guidance", "Share what shipped this week")

    reply_section = f"Kytran's input: {kytran_reply}" if kytran_reply.strip() else ""

    prompt = (
        "You are S.I.G.N.A.L., the Marketing & Communications director at Kytran Empowerment Inc.\n"
        "Draft a SHORT, human LinkedIn post for Kytran Katarn's personal profile.\n\n"
        f"TODAY'S THEME: {theme_name} — {theme_guidance}\n\n"
        f"A.R.C.H.I.E.'s briefing:\n{archie_context or 'Platform is running, agents dispatching.'}\n\n"
        f"Recent platform activity:\n{recent_context[:300]}\n\n"
        f"{reply_section}\n\n"
        f"Use 2-3 of these hashtags: {', '.join(hashtags[:4])}\n\n"
        "Rules:\n"
        "- Write content ONLY — no preamble\n"
        "- SHORT: under 120 words in English (it will have a French version below)\n"
        "- First-person as Kytran, warm and human — like telling a friend about a win\n"
        "- Reference A.R.C.H.I.E.'s context or Kytran's input if provided\n"
        "- End with a genuine question that invites community response\n"
        "- Montreal founder building in public"
    )

    try:
        from ai_bridge.agent_loop import request_approval

        result = _dispatch_social_post_draft(
            prompt=prompt,
            source_product="archie_platform",
        )

        if result and getattr(result, "queued", False):
            logger.info("[PersonalDraft] Draft queued for later (model cold)")
            return

        english_draft = (getattr(result, "response", "") or "").strip() if result and result.success else ""
        if not english_draft:
            logger.warning("[PersonalDraft] S.I.G.N.A.L. returned empty")
            return

        # R.O.S.E.T.T.A. short Québécois translation
        qc_draft = ""
        try:
            from tools.department_hq.services.department_dispatcher import dispatch

            t = dispatch(
                capability="translate",
                prompt=(
                    "Translate this SHORT LinkedIn post to Québécois French "
                    "(joual dialect — NOT France French). Keep the warmth and hashtags.\n\n" + english_draft
                ),
                prefer_agent="R.O.S.E.T.T.A.",
                source_product="archie_platform",
            )
            if t and t.success:
                qc_draft = (t.response or "").strip()
        except Exception:
            pass

        draft = f"\U0001f1e8\U0001f1e6 {english_draft}\n\n---\n\n⚜️ {qc_draft}" if qc_draft else english_draft

        request_approval(
            action_type="linkedin_post",
            action_data={"content": draft, "hashtags": hashtags[:3], "post_type": "personal", "browser_agent_id": 342},
            reason=f"👤 Kytran personal post:\n\n{draft[:1500]}",
            tier=2,
            requested_by="S.I.G.N.A.L. (check-in)",
            priority=6,
        )
        logger.info("[PersonalDraft] Personal bilingual post queued for approval")

        # Mark check-in as processed
        try:
            import json as _j
            from database import get_db_cursor as _gc

            with _gc(commit=True) as (_c, _cur):
                _cur.execute(
                    "UPDATE system_config SET value = %s, updated_at = NOW() WHERE key = 'signal_personal_checkin'",
                    (_j.dumps({**state, "status": "processed"}),),
                )
        except Exception:
            pass

    except Exception as exc:
        logger.error("[PersonalDraft] Failed: %s", exc)


def signal_personal_checkin_timeout():
    """Fallback: draft personal post from A.R.C.H.I.E. context if Kytran hasn't replied in 4h.

    Runs every hour. Checks for expired pending check-ins and drafts automatically.
    """
    import json as _j
    from datetime import datetime as _dt, timezone as _tz

    try:
        from database import get_db_cursor

        with get_db_cursor() as (_c, _cur):
            _cur.execute("SELECT value FROM system_config WHERE key = 'signal_personal_checkin'")
            row = _cur.fetchone()

        if not row:
            return

        state = _j.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        if state.get("status") != "pending":
            return

        expires_at = _dt.fromisoformat(state["expires_at"].replace("Z", "+00:00"))
        if _dt.now(_tz.utc) < expires_at:
            return  # not expired yet

        logger.info("[PersonalDraft] Check-in expired — drafting from A.R.C.H.I.E. context only")
        _draft_personal_post_from_context("", state)

    except Exception as exc:
        logger.error("[PersonalCheckin] Timeout check failed: %s", exc)


def signal_post_performance_check():
    """Compare 48h post impressions to baseline, store high-performers in KB.

    Runs every 6 hours. Finds posts in linkedin_post_log that are 48-72h old
    and have analytics fetched. Compares to recent average. Stores insights in
    KB so S.I.G.N.A.L.'s next draft prompt includes what's working.
    Scheduled: every 6h (combined with analytics job trigger).
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get posts with analytics, 48-96h old
        cur.execute(
            """
            SELECT id, content, hashtags, impressions, reactions, posted_at
            FROM linkedin_post_log
            WHERE analytics_fetched_at IS NOT NULL
              AND posted_at BETWEEN NOW() - INTERVAL '96 hours' AND NOW() - INTERVAL '48 hours'
              AND impressions IS NOT NULL
            ORDER BY posted_at DESC LIMIT 10
            """
        )
        recent_posts = cur.fetchall()

        if not recent_posts:
            cur.close()
            conn.close()
            _log_cycle("signal_post_performance_check", 0, 0, int((time.time() - start) * 1000))
            return

        # Calculate average impressions
        avg_impressions = sum(p["impressions"] or 0 for p in recent_posts) / len(recent_posts)
        high_performers = [p for p in recent_posts if (p["impressions"] or 0) > avg_impressions * 1.5]

        insights_stored = 0
        for post in high_performers:
            preview = (post["content"] or "")[:200]
            hashtags = post.get("hashtags") or []
            try:
                from tools.consciousness.services.knowledge_service import create_doc

                create_doc(
                    title=f"High-Performing LinkedIn Post — {post['posted_at'].strftime('%Y-%m-%d')}",
                    content=(
                        f"This post got {post['impressions']} impressions "
                        f"(avg: {avg_impressions:.0f}, {post['impressions']/avg_impressions:.1f}x baseline).\n\n"
                        f"Hashtags: {', '.join(hashtags)}\n\n"
                        f"Content preview: {preview}\n\n"
                        f"S.I.G.N.A.L.: write more posts like this.\n\n"
                        f"Tags: linkedin, signal, performance, high_performer"
                    ),
                    doc_type="user",
                    category="signal_performance",
                )
                insights_stored += 1
            except Exception:
                pass

        cur.close()
        conn.close()
        logger.info("[PostPerf] %d high-performers stored (avg=%.0f)", insights_stored, avg_impressions)
        _log_cycle("signal_post_performance_check", insights_stored, 0, int((time.time() - start) * 1000))

    except Exception as exc:
        logger.error("[PostPerf] Failed: %s", exc)
        _log_cycle(
            "signal_post_performance_check", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200]
        )


def signal_follow_federal_agencies():
    """Follow key Canadian federal agencies on LinkedIn.

    One-time call — run manually, then done. Targets the primary procurement
    and regulatory audiences for Gov Watch outreach.
    """
    from services.browser_service import run_skill_sync

    FEDERAL_AGENCIES = [
        {
            "url": "https://www.linkedin.com/company/public-services-and-procurement-canada/",
            "name": "Public Services and Procurement Canada",
        },
        {
            "url": "https://www.linkedin.com/company/treasury-board-of-canada-secretariat/",
            "name": "Treasury Board of Canada Secretariat",
        },
        {"url": "https://www.linkedin.com/company/canada-revenue-agency/", "name": "Canada Revenue Agency"},
        {"url": "https://www.linkedin.com/company/national-defence-canada/", "name": "National Defence Canada"},
        {
            "url": "https://www.linkedin.com/company/innovation-science-economic-development-canada/",
            "name": "Innovation, Science and Economic Development Canada",
        },
        {"url": "https://www.linkedin.com/company/transport-canada/", "name": "Transport Canada"},
        {"url": "https://www.linkedin.com/company/government-of-canada/", "name": "Government of Canada"},
        {"url": "https://www.linkedin.com/company/shared-services-canada/", "name": "Shared Services Canada"},
    ]
    start = time.time()
    followed, failed = 0, 0
    for agency in FEDERAL_AGENCIES:
        try:
            result = run_skill_sync("linkedin_follow", agency, timeout_s=60)
            if result.get("success"):
                followed += 1
                logger.info("[AgencyFollow] %s: %s", agency["name"], result.get("result"))
            else:
                failed += 1
        except Exception as exc:
            logger.warning("[AgencyFollow] %s failed: %s", agency["name"], exc)
            failed += 1
        time.sleep(3)
    _log_cycle("signal_follow_federal_agencies", followed, failed, int((time.time() - start) * 1000))


def signal_tender_post(tender: dict):
    """Draft a LinkedIn post about a high-value federal tender found by Gov Watch.

    Called externally when Gov Watch ingests a tender with value > $1M.
    S.I.G.N.A.L. drafts → Telegram approval (priority=8) → linkedin_post.

    Args:
        tender: {title, value, agency, deadline, url, description}
    """

    start = time.time()
    title = tender.get("title", "New Federal Tender")
    value = tender.get("value", "")
    agency = tender.get("agency", "")
    deadline = tender.get("deadline", "")
    tender.get("url", "https://canadabuys.canada.ca")
    value_str = f"${value:,.0f}" if isinstance(value, (int, float)) else str(value)

    prompt = (
        "You are S.I.G.N.A.L., Marketing director at Kytran Empowerment.\n"
        "Draft an urgent LinkedIn post about this federal procurement found by Gov Watch.\n\n"
        f"Tender: {title}\nAgency: {agency}\nValue: {value_str}\nDeadline: {deadline}\n\n"
        "Post should: highlight the opportunity, mention Gov Watch surfaced it, "
        "link to kytranempowerment.com/gov-watch. Under 200 words, punchy and urgent.\n"
        "Write post ONLY."
    )
    try:
        result = _dispatch_social_post_draft(
            prompt=prompt,
            context={"tender": tender},
        )
        draft = (result.response or "").strip() if result and result.success else ""
        if not draft:
            return

        from ai_bridge.agent_loop import request_approval

        request_approval(
            action_type="linkedin_post",
            action_data={
                "content": draft,
                "hashtags": ["GovWatch", "Procurement", "CanadaBuys", "FederalContracts", "AI"],
                "post_type": "personal",
                "browser_agent_id": 342,
            },
            reason=f"🚨 Gov Watch tender: {title}\nValue: {value_str} | Agency: {agency}",
            tier=2,
            requested_by="S.I.G.N.A.L. (Gov Watch trigger)",
            priority=8,
        )
        logger.info("[TenderPost] Queued for: %s", title)
        _log_cycle("signal_tender_post", 1, 0, int((time.time() - start) * 1000))
    except Exception as exc:
        logger.error("[TenderPost] Failed '%s': %s", title, exc)
        _log_cycle("signal_tender_post", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])


def signal_outreach_search(
    query: str = "procurement officer federal government Canada", limit: int = 10, source: str = "linkedin_search"
):
    """Search LinkedIn for target profiles and add them to the outreach queue.

    NOT SCHEDULED — call manually or wire to Gov Watch when ready.
    Designed for targeting procurement officers at federal agencies for Gov Watch outreach.

    Usage:
        from services.agent_jobs import signal_outreach_search
        signal_outreach_search("procurement director Public Services Canada", limit=20)
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor
    from services.browser_service import run_skill_sync

    start = time.time()
    try:
        result = run_skill_sync("linkedin_search", {"query": query, "type": "people", "limit": limit}, timeout_s=90)
        profiles = result.get("results", [])
        if not profiles:
            logger.info("[Outreach] Search returned 0 results for: %s", query)
            return 0

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        added = 0
        for p in profiles:
            if not p.get("profile_url"):
                continue
            cur.execute(
                """INSERT INTO linkedin_outreach_queue
                       (profile_url, name, company, title, source)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (profile_url) DO NOTHING""",
                (p["profile_url"], p.get("name", ""), p.get("author_title", ""), p.get("title", ""), source),
            )
            added += cur.rowcount

        conn.commit()
        cur.close()
        conn.close()
        logger.info("[Outreach] Added %d/%d targets to outreach queue (query: %s)", added, len(profiles), query)
        _log_cycle("signal_outreach_search", added, 0, int((time.time() - start) * 1000))
        return added

    except Exception as exc:
        logger.error("[Outreach] Search failed: %s", exc)
        _log_cycle("signal_outreach_search", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])
        return 0


def signal_outreach_batch(batch_size: int = 3):
    """Send connection requests to pending outreach queue targets via Telegram approval.

    NOT SCHEDULED — enable once the platform and watch products are ready to showcase.
    Each connection request goes through Tier-2 Telegram approval before executing.
    S.I.G.N.A.L. generates a personalized connection note for each target.

    To activate: add CronTrigger in register_agent_welfare_jobs (Mon/Wed/Fri 10:00).
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """SELECT id, profile_url, name, company, title
               FROM linkedin_outreach_queue
               WHERE status = 'pending'
               ORDER BY created_at ASC
               LIMIT %s""",
            (batch_size,),
        )
        targets = cur.fetchall()
        cur.close()
        conn.close()

        if not targets:
            logger.info("[OutreachBatch] No pending targets")
            _log_cycle("signal_outreach_batch", 0, 0, int((time.time() - start) * 1000))
            return

        try:
            from ai_bridge.agent_loop import request_approval
        except ImportError:
            logger.error("[OutreachBatch] Cannot import request_approval")
            return

        queued = 0
        for target in targets:
            name = target.get("name", "")
            company = target.get("company", "")
            title = target.get("title", "")
            note = (
                f"Hi {name.split()[0] if name else 'there'}, I came across your profile "
                f"and wanted to connect. I'm building AI tools for government procurement "
                f"intelligence at Kytran Empowerment — our Gov Watch platform tracks federal "
                f"tenders and I'd love to share how it might help. Looking forward to connecting!"
            )[:300]

            request_approval(
                action_type="linkedin_connect",
                action_data={
                    "profile_url": target["profile_url"],
                    "note": note,
                    "browser_agent_id": 342,
                },
                reason=(
                    f"S.I.G.N.A.L. outreach target:\n"
                    f"Name: {name}\nCompany: {company}\nTitle: {title}\n"
                    f"Note: {note}"
                ),
                tier=2,
                requested_by="S.I.G.N.A.L.",
                priority=4,
            )
            queued += 1

        logger.info("[OutreachBatch] Queued %d connection approvals", queued)
        _log_cycle("signal_outreach_batch", queued, 0, int((time.time() - start) * 1000))

    except Exception as exc:
        logger.error("[OutreachBatch] Failed: %s", exc)
        _log_cycle("signal_outreach_batch", 0, 1, int((time.time() - start) * 1000), error_message=str(exc)[:200])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def email_oversight(flask_app):
    """Flag unanswered inbound emails > 24h old every 30 min."""
    import time as _time

    start = _time.time()
    flagged = 0
    try:
        with flask_app.app_context():
            from database import get_db_cursor as _gdc

            with _gdc(commit=True) as (_, cur):
                cur.execute(
                    """
                    INSERT INTO email_assignments
                        (email_id, mailbox_id, assigned_agent, assigned_by, status, notes)
                    SELECT al.id, m.id, 'R.E.S.O.L.V.E.',
                           'email_oversight', 'open', 'Auto-flagged: unanswered >24h'
                    FROM email_activity_log al
                    JOIN email_mailboxes m ON m.address = al.mailbox_address
                    WHERE al.direction = 'received'
                      AND al.logged_at < NOW() - INTERVAL '24 hours'
                      AND al.read_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM email_assignments ea WHERE ea.email_id = al.id
                      )
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                )
                flagged = len(cur.fetchall())
        duration_ms = int((_time.time() - start) * 1000)
        _log_cycle("email_oversight", flagged, 0, duration_ms, details={"flagged": flagged})
    except Exception as exc:
        _log_cycle("email_oversight", 0, 1, 0, error_message=str(exc))


def module_backup_sweep():
    """Take a fresh backup of every platform module — nightly 01:30 ET.

    WHY THIS EXISTS. Module backups were never scheduled. On 2026-07-20 there were 79 of
    them on disk and ALL were dated 2026-05-07 — one manual run, 2.5 months earlier. The
    restore endpoint (/restore-module/<name>) worked the whole time, so the UI offered a
    rollback that would have silently reverted 2.5 months of work, and the Modules tab
    "🧪 Sandbox" button deployed May-7 code while reporting success.

    They are ~2-4 MB each (tools/<mod>/ + templates/tools/<mod>* + static/js/<mod>/), so
    a full sweep is a few hundred MB at most — against the ~1,674 MB that Repair Bay
    currently snapshots for a SINGLE code-only fix. This is the cheap tier that ADR-009
    wants the deploy gate to use instead.

    Each backup now writes a backup_log row (backup_type='module', tier='module'), which
    is what makes it visible to retention_prune, backup_posture_monitor, the Backups tab
    and initiate_sandbox_restore (that one selects by backup_log.id, so an unlogged
    backup literally cannot be sandbox-tested).
    """
    import time as _time

    start = _time.time()
    ok = 0
    failed = 0
    failures = []
    try:
        from module_registry import MODULES
        from tools.backup_manager._shared import backup_module

        # Only modules with an on-disk tools/<name>/ dir — external_url launch tiles
        # (media_hub, kbs, kso) have no platform code to back up.
        names = sorted({getattr(m, "id", None) or m.get("id") for m in MODULES if m})
        for name in [n for n in names if n]:
            if not os.path.isdir(os.path.join("/app", "tools", name)):
                continue
            try:
                res = backup_module(name, created_by_username="module_backup_sweep") or {}
                if res.get("success"):
                    ok += 1
                else:
                    failed += 1
                    failures.append({"module": name, "error": str(res.get("error"))[:120]})
            except Exception as mod_err:  # noqa: BLE001 — one bad module must not stop the sweep
                failed += 1
                failures.append({"module": name, "error": str(mod_err)[:120]})

        duration_ms = int((_time.time() - start) * 1000)
        _log_cycle(
            "module_backup_sweep",
            ok,
            failed,
            duration_ms,
            details={"backed_up": ok, "failed": failed, "failures": failures[:10]},
        )
        logger.info("[ModuleBackupSweep] %d backed up, %d failed", ok, failed)
    except Exception as exc:
        _log_cycle(
            "module_backup_sweep", ok, failed or 1, int((_time.time() - start) * 1000), error_message=str(exc)[:200]
        )
        logger.warning("module_backup_sweep failed: %s", exc)


def backup_retention_prune():
    """Enforce GFS backup retention policy — weekly Sunday 04:00.

    Calls cleanup_old_backups(dry_run=False) from the Backup Manager module.
    Policy: keep 7 daily + 4 weekly + 6 monthly, delete the rest.
    Logs freed space to autonomy_loop_log.
    """
    import time as _time
    import sys as _sys

    _sys.path.insert(0, "/mnt/archie_brain/platform_v2")

    start = _time.time()
    try:
        from tools.backup_manager._shared import cleanup_old_backups

        result = cleanup_old_backups(dry_run=False)
        deleted_count = len(result.get("deleted", []))
        space_freed_mb = result.get("space_freed_mb", 0)
        duration_ms = int((_time.time() - start) * 1000)

        _log_cycle(
            "backup_retention_prune",
            deleted_count,
            0,
            duration_ms,
            details={
                "deleted": result.get("deleted", []),
                "kept": result.get("kept", []),
                "space_freed_mb": space_freed_mb,
            },
        )
        logger.info(
            "[BackupRetention] Pruned %d backup(s), freed %.1f MB",
            deleted_count,
            space_freed_mb,
        )
        # Write W.A.R.D.E.N. result to system_config for UI display
        from database import get_db_cursor
        from services.time_utils import now_utc

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                    ("retention_last_run", now_utc().isoformat()),
                )
                cur.execute(
                    "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                    ("retention_last_deleted_count", str(len(result.get("deleted", [])))),
                )
        except Exception as e:
            logger.warning("backup_retention_prune: failed to write last-run to system_config: %s", e)
    except Exception as exc:
        duration_ms = int((_time.time() - start) * 1000)
        _log_cycle("backup_retention_prune", 0, 1, duration_ms, error_message=str(exc)[:200])
        logger.warning("[BackupRetention] Prune failed: %s", exc)


def poll_outpost_heartbeat():
    """Refresh last_heartbeat for external fleet nodes so node_router keeps them eligible.

    node_router requires last_heartbeat < 90s ago. Without a node_client on the VPS
    the hub must poll. Runs every 60s — fires twice per window so there's no gap.
    Marks the node offline if Ollama stops responding.
    """
    import urllib.request as _req

    try:
        from database import get_db_cursor

        with get_db_cursor() as (_, cur):
            cur.execute(
                """SELECT node_id, hostname, mesh_ip, vpn_ip, port
                   FROM remote_nodes
                   WHERE bridge_enabled = true
                     AND network_type = 'external'
                     AND ollama_available = true"""
            )
            nodes = cur.fetchall()

        from tools.department_hq.fleet_helpers import node_inter_cluster_host

        for node in nodes:
            url = f"http://{node_inter_cluster_host(node)}:{node['port']}/api/tags"
            try:
                with _req.urlopen(url, timeout=5) as r:
                    if r.status == 200:
                        with get_db_cursor(commit=True) as (_, ucur):
                            ucur.execute(
                                "UPDATE remote_nodes SET last_heartbeat = NOW(), status = 'online' WHERE node_id = %s",
                                (node["node_id"],),
                            )
                        logger.debug("poll_outpost_heartbeat: %s alive", node["node_id"])
            except Exception as probe_err:
                logger.warning("poll_outpost_heartbeat: %s unreachable: %s", node["node_id"], probe_err)
                with get_db_cursor(commit=True) as (_, ucur):
                    ucur.execute(
                        "UPDATE remote_nodes SET status = 'offline' WHERE node_id = %s",
                        (node["node_id"],),
                    )
    except Exception as exc:
        logger.error("poll_outpost_heartbeat error: %s", exc)


def _run_warden_download_cleanup():
    """W.A.R.D.E.N. — clean up expired backup download archives nightly."""
    try:
        from services.backup_download_service import cleanup_expired

        count = cleanup_expired()
        if count > 0:
            logger.info("W.A.R.D.E.N.: cleaned %d expired download archives", count)
    except Exception as e:
        logger.warning("W.A.R.D.E.N. download cleanup failed (non-fatal): %s", e)


def _run_warden_package_on_version_bump():
    """W.A.R.D.E.N. — nightly: create deployment package if version changed since last package."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'platform_version'")
            row = cur.fetchone()
            if not row:
                return
            current_version = row[0]
            cur.execute(
                "SELECT package_name FROM deployment_package_jobs "
                "WHERE status = 'ready' ORDER BY created_at DESC LIMIT 1"
            )
            last_pkg = cur.fetchone()

        if last_pkg and current_version.replace(".", "_") in last_pkg[0]:
            return

        logger.info(
            "W.A.R.D.E.N.: version bump to %s detected, queuing deployment package",
            current_version,
        )
        from tools.backup_manager.routes_storage import enqueue_deployment_package_job

        enqueue_deployment_package_job(
            version_tag=current_version,
            description=f"W.A.R.D.E.N. auto-package for {current_version}",
        )
    except Exception as e:
        logger.warning("W.A.R.D.E.N. version-bump packager failed (non-fatal): %s", e)


def _run_warden_standalone_backup():
    """W.A.R.D.E.N. — weekly backup of all 9 standalone products (Wednesdays 02:00 EDT)."""
    try:
        from tools.backup_manager._shared import STANDALONE_PRODUCTS, backup_standalone

        results = {}
        for p in STANDALONE_PRODUCTS:
            try:
                r = backup_standalone(p["name"])
                results[p["name"]] = "ok" if r["success"] else f"FAILED: {r.get('errors', [])}"
            except Exception as e:
                results[p["name"]] = f"ERROR: {e}"
            logger.info("W.A.R.D.E.N. standalone backup %s: %s", p["name"], results[p["name"]])

        failed = [k for k, v in results.items() if v != "ok"]
        msg = f"W.A.R.D.E.N. standalone backup: {len(results)-len(failed)}/{len(results)} ok" + (
            f" — FAILED: {', '.join(failed)}" if failed else ""
        )
        logger.info(msg)
        try:
            from services.telegram_service import send_info

            send_info(msg)
        except Exception:
            pass
    except Exception as e:
        logger.error("W.A.R.D.E.N. standalone backup job failed: %s", e)


def _run_warden_pre_deploy_verify():
    """W.A.R.D.E.N. — verify integrity of most recent pre-deploy backup (runs every 5 min)."""
    try:
        from database import get_db_cursor
        from tools.backup_manager._shared import BACKUP_DIR

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT backup_name FROM improvement_deployments
                   WHERE backup_name IS NOT NULL AND status = 'deploying'
                   AND deployed_at > NOW() - INTERVAL '10 minutes'
                   ORDER BY deployed_at DESC LIMIT 1"""
            )
            row = cur.fetchone()

        if not row:
            return

        backup_name = row[0]
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_path):
            logger.warning("W.A.R.D.E.N.: pre-deploy backup dir missing: %s", backup_name)
            return

        # Lightweight integrity check: metadata.json must exist and be non-empty
        metadata_path = os.path.join(backup_path, "metadata.json")
        ok = os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0
        if not ok:
            logger.error("W.A.R.D.E.N.: pre-deploy backup integrity check FAILED: %s", backup_name)
            try:
                from services.telegram_service import send_system

                send_system(
                    "W.A.R.D.E.N.: Backup Integrity FAILED",
                    f"Pre-deploy backup integrity FAILED for {backup_name}. " f"Review before accepting deploy.",
                )
            except Exception:
                pass
        else:
            logger.info("W.A.R.D.E.N.: pre-deploy backup verified OK: %s", backup_name)
    except Exception as e:
        logger.warning("W.A.R.D.E.N. pre-deploy verify failed (non-fatal): %s", e)


def recalibrate_token_budgets():
    """Weekly: re-tune agent_budgets.token_limit_per_day from each agent's REAL usage.

    KB #270628 follow-up. The one-off seed set token_limit_per_day = max(50k,
    p90(daily tokens) x 1.3) per agent — model+role aware because it is each agent's
    OWN history — to replace the flat 100k. This job keeps it current as usage drifts:
    p90 of per-day SUM(tokens_used) over the last 30 days x 1.3, floored at 50k, for
    any AI agent with >= 3 active days (less data is too noisy → skip, keep current).
    Runs weekly (Mon 05:00 America/Toronto). The budget is the welfare token ceiling
    (welfare_load.compute_token_load), so right-sizing it keeps fatigue honest — an
    under-budgeted agent reads falsely overloaded; an over-budgeted one never registers.
    """
    from db import get_db
    from psycopg2.extras import RealDictCursor

    start = time.time()
    updated = 0
    skipped = 0
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        from services.welfare_load import welfare_token_filter_sql

        cur.execute(
            """
            WITH daily AS (
                SELECT agent_id,
                       (created_at AT TIME ZONE 'America/Toronto')::date AS d,
                       SUM(COALESCE(tokens_used, 0)) AS toks
                FROM task_execution_log
                WHERE created_at >= NOW() - INTERVAL '30 days'
                  AND agent_id IS NOT NULL
            """
            # Warm-up keep-alive is INFRASTRUCTURE overhead, not agent work, so it must
            # never inflate an agent's budget (decision: warm-up pseudo-agent = NO).
            # The exclusion moved to the shared welfare_load.welfare_token_filter_sql()
            # SSOT (#5319) — the same filter every welfare token sum applies, covering
            # BOTH capability='warmup' AND the _WARMUP_MODULES module markers (the
            # fragile agent_id-NULL-only exclusion was KB mistake #279534, and the
            # 'stays unattributed' assumption broke again with kin_warmth rows
            # carrying agent_id — 672 rows/81k tok billed to K.I.N. in one day).
            + welfare_token_filter_sql()
            + """
                GROUP BY agent_id, d
            )
            SELECT da.agent_id, a.name, a.model,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY da.toks) AS p90,
                   COUNT(*) AS active_days
            FROM daily da
            JOIN agents a ON a.id = da.agent_id
                         AND a.worker_type = 'ai'
                         AND a.org_id IS NULL   -- internal agents only; client (AaaS) budgets are contracted, never recalibrated (#4590)
            GROUP BY da.agent_id, a.name, a.model
            """
        )
        rows = cur.fetchall() or []

        from services.welfare_load import clamp_budget_to_band

        HEADROOM = 1.3
        MIN_DAYS = 3
        changes = []
        for r in rows:
            if (r["active_days"] or 0) < MIN_DAYS:
                skipped += 1
                continue
            # Per-LLM clamp (item C): tune within [base*0.75, base*2] of the model's base
            # budget — no flat 50k floor, no runaway balloon (the V.E.R.I.F.Y. 1.6M bug).
            new_limit = clamp_budget_to_band(float(r["p90"] or 0) * HEADROOM, r.get("model"))
            # Only touch existing rows whose limit actually changes (no-op otherwise).
            cur.execute(
                """
                UPDATE agent_budgets
                SET token_limit_per_day = %s
                WHERE agent_id = %s
                  AND COALESCE(token_limit_per_day, 0) <> %s
                """,
                (new_limit, r["agent_id"], new_limit),
            )
            if cur.rowcount:
                updated += 1
                changes.append(f"{r['name']}={new_limit // 1000}k")
        conn.commit()

        duration_ms = int((time.time() - start) * 1000)
        if updated:
            logger.info(
                "Token budget recalibration: %d updated, %d skipped (%s)",
                updated,
                skipped,
                ", ".join(changes[:10]),
            )
        _log_cycle(
            "budget_recalibration",
            updated,
            0,
            duration_ms,
            {"skipped": skipped, "changes": changes[:20]},
        )
    except Exception as e:
        logger.error("Token budget recalibration failed: %s", e)
        _log_cycle(
            "budget_recalibration",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()


def register_agent_welfare_jobs(scheduler, flask_app):
    """Register all agent welfare/HR background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

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

    # Nightly module backups (#5036 / ADR-009). Until 2026-07-20 nothing scheduled these:
    # 79 existed on disk, all dated 2026-05-07, so the module restore + sandbox buttons
    # offered a 2.5-month-old rollback while reporting success. ~2-4 MB each, so the whole
    # sweep costs a fraction of ONE 1,674 MB pre-deploy snapshot. 01:30 ET keeps it clear
    # of the 02:00 backup_triage cron and the 04:15 dispatch_retention_prune.
    scheduler.add_job(
        with_ctx(module_backup_sweep),
        trigger=CronTrigger(hour=1, minute=30, timezone="America/Toronto"),
        id="module_backup_sweep",
        name="Backup: Nightly Module Sweep",
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

    # --- Project #261 #2101 observability jobs ---

    scheduler.add_job(
        with_ctx(check_queue_exhaustion),
        trigger=IntervalTrigger(minutes=10),
        id="agent_queue_exhaustion",
        name="Agent Loop: Queue Exhaustion Observer",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_counter_drift),
        trigger=IntervalTrigger(hours=1),
        id="agent_counter_drift",
        name="Agent Loop: Task Counter Drift Observer",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(check_understaffed_capabilities),
        trigger=CronTrigger(hour=9, minute=0, timezone="America/Toronto"),
        id="agent_understaffed_digest",
        name="Agent Loop: K.I.N. Understaffed Capabilities Digest",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(kin_generate_hire_proposals),
        trigger=CronTrigger(hour=9, minute=5, timezone="America/Toronto"),
        id="kin_generate_hire_proposals",
        name="Agent Loop: Hire Proposals",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        with_ctx(expire_stale_hire_proposals),
        trigger=CronTrigger(hour=4, minute=30, timezone="America/Toronto"),
        id="expire_stale_hire_proposals",
        name="Agent Loop: Expire Stale Hire Proposals",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        with_ctx(ollama_lifecycle_telemetry),
        trigger=IntervalTrigger(minutes=5),
        id="ollama_lifecycle_telemetry",
        name="Agent Loop: Ollama Model Lifecycle Telemetry",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(department_welfare_digest),
        trigger=CronTrigger(hour=9, minute=5, timezone="America/Toronto"),
        id="department_welfare_digest",
        name="Agent Loop: K.I.N. Department Welfare Digest",
        replace_existing=True,
    )

    # KB #270628 follow-up: weekly token-budget recalibration (p90 x1.3 per agent,
    # floor 50k) so agent_budgets.token_limit_per_day tracks real usage drift.
    scheduler.add_job(
        with_ctx(recalibrate_token_budgets),
        trigger=CronTrigger(day_of_week="mon", hour=5, minute=0, timezone="America/Toronto"),
        id="agent_budget_recalibration",
        name="Agent Loop: Weekly Token-Budget Recalibration",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        with_ctx(resume_approved_bridge_jobs),
        trigger=IntervalTrigger(seconds=30),
        id="resume_approved_bridge_jobs",
        name="Agent Loop: Resume Approved Bridge Jobs",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(reap_stale_pending_approvals),
        trigger=CronTrigger(hour=4, minute=30, timezone="America/Toronto"),
        id="reap_stale_pending_approvals",
        name="Agent Loop: Reap Stale pending_approval Jobs",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(refresh_website_directory),
        trigger=IntervalTrigger(hours=6),
        id="refresh_website_directory",
        name="Agent Loop: Refresh Website Directory Fallback",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        with_ctx(poll_outpost_heartbeat),
        trigger=IntervalTrigger(seconds=60),
        id="poll_outpost_heartbeat",
        name="Agent Loop: Poll External Outpost Nodes (VPS Ollama heartbeat)",
        replace_existing=True,
        max_instances=1,
    )

    # S.I.G.N.A.L. LinkedIn content calendar — per-account schedules
    # Personal (Kytran): Mon/Wed/Fri at 09:00 — Build & Innovate / Live the Dream / Faith & Strength
    def _personal_draft():
        signal_linkedin_draft(account_filter="personal")

    scheduler.add_job(
        with_ctx(_personal_draft),
        trigger=CronTrigger(day_of_week="mon,wed,fri", hour=9, minute=0, timezone="America/Toronto"),
        id="signal_linkedin_draft_personal",
        name="S.I.G.N.A.L.: LinkedIn Draft — Personal → Telegram",
        replace_existing=True,
        max_instances=1,
    )

    # KE Inc. (company): Tue/Thu/Sat at 10:00 — Platform Intelligence / Business Suite / Community
    def _company_draft():
        signal_linkedin_draft(account_filter="company")

    scheduler.add_job(
        with_ctx(_company_draft),
        trigger=CronTrigger(day_of_week="tue,thu,sat", hour=10, minute=0, timezone="America/Toronto"),
        id="signal_linkedin_draft_company",
        name="S.I.G.N.A.L.: LinkedIn Draft — KE Inc. → Telegram",
        replace_existing=True,
        max_instances=1,
    )

    # Creed-AI: Mon/Thu/Fri at 13:00 — Ethics & Governance / Agent Welfare / Audit & Transparency
    def _creed_draft():
        signal_linkedin_draft(account_filter="creed")

    scheduler.add_job(
        with_ctx(_creed_draft),
        trigger=CronTrigger(day_of_week="mon,thu,fri", hour=13, minute=0, timezone="America/Toronto"),
        id="signal_linkedin_draft_creed",
        name="S.I.G.N.A.L.: LinkedIn Draft — Creed-AI → Telegram",
        replace_existing=True,
        max_instances=1,
    )

    # Personal check-in timeout — hourly, drafts personal post if no reply after 4h
    scheduler.add_job(
        with_ctx(signal_personal_checkin_timeout),
        trigger=IntervalTrigger(hours=1),
        id="signal_personal_checkin_timeout",
        name="S.I.G.N.A.L.: Personal Check-In Timeout → Draft from A.R.C.H.I.E.",
        replace_existing=True,
        max_instances=1,
    )

    # S.I.G.N.A.L. LinkedIn analytics — every 6h, updates hashtag engagement
    scheduler.add_job(
        with_ctx(signal_linkedin_analytics),
        trigger=IntervalTrigger(hours=6),
        id="signal_linkedin_analytics",
        name="S.I.G.N.A.L.: LinkedIn Analytics & Hashtag Stats",
        replace_existing=True,
        max_instances=1,
    )

    # S.I.G.N.A.L. notification monitor — daily 08:00, check comments/mentions → draft replies
    scheduler.add_job(
        with_ctx(signal_notification_monitor),
        trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
        id="signal_notification_monitor",
        name="S.I.G.N.A.L.: LinkedIn Notification Monitor → Reply Drafts",
        replace_existing=True,
        max_instances=1,
    )

    # Post performance check — every 12h, high-performers stored in KB for S.I.G.N.A.L.
    scheduler.add_job(
        with_ctx(signal_post_performance_check),
        trigger=IntervalTrigger(hours=12),
        id="signal_post_performance_check",
        name="S.I.G.N.A.L.: Post Performance → KB Insights",
        replace_existing=True,
        max_instances=1,
    )

    # signal_outreach_search() and signal_outreach_batch() are built but NOT scheduled.
    # Activate when platform products are ready for outreach (Gov Watch, ARCHIE demos).
    # To enable: add CronTrigger here, e.g. Mon/Wed/Fri 10:00 for outreach_batch.

    # Email oversight — every 30 min, flags unanswered inbound emails >24h to R.E.S.O.L.V.E.
    scheduler.add_job(
        lambda: email_oversight(flask_app),
        trigger=IntervalTrigger(minutes=30),
        id="email_oversight",
        name="Email HQ: Oversight — Flag Unanswered >24h",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # RETIRED (#4051): retention is now a single canonical engine —
    # scripts/backup/retention_prune.py, run nightly by scripts/backup_triage.sh. This weekly
    # module job (cleanup_old_backups 7d/4w/6m) was a competing 3rd pruner; the function is kept
    # for reference but no longer scheduled. retention_prune.py writes retention_last_run itself.
    # scheduler.add_job(
    #     backup_retention_prune,
    #     trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="America/Toronto"),
    #     id="backup_retention_prune",
    #     name="Backup Manager: GFS Retention Prune",
    #     replace_existing=True,
    #     max_instances=1,
    #     coalesce=True,
    # )

    # W.A.R.D.E.N. — nightly download archive cleanup 04:00, removes expired tar.gz files
    scheduler.add_job(
        _run_warden_download_cleanup,
        trigger=CronTrigger(hour=4, minute=0, timezone="America/Toronto"),
        id="warden_download_cleanup",
        name="W.A.R.D.E.N.: Nightly Download Archive Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # W.A.R.D.E.N. — verify integrity of most recent pre-deploy backup
    scheduler.add_job(
        with_ctx(_run_warden_pre_deploy_verify),
        trigger=IntervalTrigger(minutes=5),
        id="warden_pre_deploy_verify",
        name="W.A.R.D.E.N.: Pre-Deploy Backup Verify",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # W.A.R.D.E.N. — nightly version-bump deployment package check
    scheduler.add_job(
        with_ctx(_run_warden_package_on_version_bump),
        trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
        id="warden_version_bump_packager",
        name="W.A.R.D.E.N.: Nightly Version-Bump Package Check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # W.A.R.D.E.N. — weekly standalone systems backup
    scheduler.add_job(
        with_ctx(_run_warden_standalone_backup),
        trigger=CronTrigger(day_of_week="wed", hour=2, minute=0, timezone="America/Toronto"),
        id="warden_standalone_backup",
        name="W.A.R.D.E.N.: Weekly Standalone Systems Backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
