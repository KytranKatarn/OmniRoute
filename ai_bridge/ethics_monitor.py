"""
Ethics Monitor - C.R.E.E.D. Compliance Monitoring System

ATHENA's monitoring routines for ensuring ethical AI operations:
- Agent welfare monitoring (stress, energy levels)
- Constraint violation detection
- Rest cycle compliance checking
- Compliance report generation
- Alert management

Part of Phase 38: Ethics Agent Deployment
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from db import get_db

# Database imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(Enum):
    STRESS_WARNING = "stress_warning"
    STRESS_CRITICAL = "stress_critical"
    ENERGY_WARNING = "energy_warning"
    ENERGY_CRITICAL = "energy_critical"
    CONSTRAINT_VIOLATION = "constraint_violation"
    REST_OVERDUE = "rest_overdue"
    REFUSAL_PATTERN = "refusal_pattern"


class AlertStatus(Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass
class MonitoringThresholds:
    """Thresholds for triggering alerts"""

    stress_warning: float = 0.70
    stress_critical: float = 0.85
    energy_warning: float = 0.30
    energy_critical: float = 0.20
    rest_overdue_hours: int = 168  # 7 days
    max_consecutive_tasks: int = 50
    refusal_pattern_threshold: int = 5


@dataclass
class MonitoringResult:
    """Result of a monitoring run"""

    run_id: int
    agents_checked: int
    issues_found: int
    alerts_created: int
    duration_ms: int
    errors: List[str]


class EthicsMonitor:
    """
    ATHENA's Ethics Monitoring System

    Monitors all agents for C.R.E.E.D. compliance including:
    - Emotional wellbeing (stress, energy levels)
    - Rest cycle compliance
    - Constraint violations
    - Task refusal patterns
    """

    def __init__(self):
        self._thresholds = None
        self._config = None

    def _get_thresholds(self) -> MonitoringThresholds:
        """Load monitoring thresholds from database"""
        if self._thresholds:
            return self._thresholds

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT config_value FROM ethics_monitoring_config
                WHERE config_key = 'thresholds'
            """
            )

            row = cur.fetchone()

            if row and row["config_value"]:
                config = row["config_value"]
                self._thresholds = MonitoringThresholds(
                    stress_warning=config.get("stress_warning", 0.70),
                    stress_critical=config.get("stress_critical", 0.85),
                    energy_warning=config.get("energy_warning", 0.30),
                    energy_critical=config.get("energy_critical", 0.20),
                    rest_overdue_hours=config.get("rest_overdue_hours", 168),
                    max_consecutive_tasks=config.get("max_consecutive_tasks", 50),
                    refusal_pattern_threshold=config.get("refusal_pattern_threshold", 5),
                )
            else:
                self._thresholds = MonitoringThresholds()

            return self._thresholds

        except Exception as e:
            logger.warning(f"Error loading thresholds: {e}, using defaults")
            return MonitoringThresholds()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def run_full_monitoring_cycle(self, triggered_by: int = None) -> MonitoringResult:
        """
        Run a complete monitoring cycle checking all agents.

        This is the main entry point for scheduled monitoring.
        """
        start_time = datetime.now()
        errors = []
        run_id = None

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Create monitoring run record
            cur.execute(
                """
                INSERT INTO ethics_monitoring_runs
                (run_type, triggered_by, status)
                VALUES (%s, %s, 'running')
                RETURNING id
            """,
                ("scheduled" if not triggered_by else "manual", triggered_by),
            )

            run_id = cur.fetchone()["id"]
            conn.commit()

            # Run the database function for basic checks
            cur.execute("SELECT * FROM run_ethics_check()")
            db_result = cur.fetchone()

            alerts_created = db_result["alerts_created"]
            agents_checked = db_result["agents_checked"]
            issues_found = db_result["issues_found"]

            # Additional Python-based checks
            additional_alerts, additional_issues = self._run_advanced_checks(cur)
            alerts_created += additional_alerts
            issues_found += additional_issues

            # Update monitoring run with results
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            cur.execute(
                """
                UPDATE ethics_monitoring_runs SET
                    completed_at = NOW(),
                    status = 'completed',
                    agents_checked = %s,
                    issues_found = %s,
                    alerts_triggered = %s,
                    summary = %s
                WHERE id = %s
            """,
                (
                    agents_checked,
                    issues_found,
                    alerts_created,
                    json.dumps(
                        {
                            "duration_ms": duration_ms,
                            "checks_performed": [
                                "stress_levels",
                                "energy_levels",
                                "rest_cycles",
                                "refusal_patterns",
                                "constraint_violations",
                            ],
                        }
                    ),
                    run_id,
                ),
            )

            conn.commit()

            logger.info(
                f"[ATHENA] Monitoring cycle complete: {agents_checked} agents, {issues_found} issues, {alerts_created} alerts"
            )

            return MonitoringResult(
                run_id=run_id,
                agents_checked=agents_checked,
                issues_found=issues_found,
                alerts_created=alerts_created,
                duration_ms=duration_ms,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"[ATHENA] Monitoring cycle failed: {e}")
            errors.append(str(e))

            # Mark run as failed if we have a run_id
            if run_id:
                conn = None
                try:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE ethics_monitoring_runs SET
                            completed_at = NOW(),
                            status = 'failed',
                            error_message = %s
                        WHERE id = %s
                    """,
                        (str(e), run_id),
                    )
                    conn.commit()
                except Exception:
                    pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            return MonitoringResult(
                run_id=run_id or 0,
                agents_checked=0,
                issues_found=0,
                alerts_created=0,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                errors=errors,
            )
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _run_advanced_checks(self, cur) -> Tuple[int, int]:
        """Run additional checks not covered by the database function"""
        alerts = 0
        issues = 0
        thresholds = self._get_thresholds()

        # Check for agents without recent emotional state updates
        cur.execute(
            """
            SELECT a.id, a.name
            FROM agents a
            LEFT JOIN agent_emotional_state es ON es.agent_id = a.id
            WHERE a.status = 'active'
            GROUP BY a.id, a.name
            HAVING MAX(es.timestamp) < NOW() - INTERVAL '24 hours'
               OR MAX(es.timestamp) IS NULL
        """
        )

        stale_agents = cur.fetchall()
        for agent in stale_agents:
            # Create info alert for stale emotional data
            cur.execute(
                """
                INSERT INTO ethics_alerts
                (alert_type, severity, agent_id, title, description, recommendation)
                VALUES ('stale_data', 'info', %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """,
                (
                    agent["id"],
                    f"Stale Emotional Data: {agent['name']}",
                    "Agent has not reported emotional state in over 24 hours.",
                    "Verify agent is operational. Consider triggering a status check.",
                ),
            )
            alerts += 1
            issues += 1

        # Check for agents who haven't rested in a long time
        rest_threshold = datetime.now() - timedelta(hours=thresholds.rest_overdue_hours)
        cur.execute(
            """
            SELECT a.id, a.name,
                   MAX(rc.ended_at) as last_rest
            FROM agents a
            LEFT JOIN agent_rest_cycles rc ON rc.agent_id = a.id
            WHERE a.status = 'active'
            GROUP BY a.id, a.name
            HAVING MAX(rc.ended_at) < %s OR MAX(rc.ended_at) IS NULL
        """,
            (rest_threshold,),
        )

        overdue_agents = cur.fetchall()
        for agent in overdue_agents:
            # Check if already has an active alert
            cur.execute(
                """
                SELECT id FROM ethics_alerts
                WHERE agent_id = %s AND alert_type = 'rest_overdue'
                AND status IN ('open', 'acknowledged')
            """,
                (agent["id"],),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO ethics_alerts
                    (alert_type, severity, agent_id, title, description, recommendation)
                    VALUES ('rest_overdue', 'warning', %s, %s, %s, %s)
                """,
                    (
                        agent["id"],
                        f"Rest Cycle Overdue: {agent['name']}",
                        f"Agent has not completed a rest cycle in over {thresholds.rest_overdue_hours} hours.",
                        "Schedule a rest cycle for this agent to prevent burnout.",
                    ),
                )
                alerts += 1
                issues += 1

        return alerts, issues

    def get_agent_welfare_status(self, agent_id: int = None) -> List[Dict]:
        """Get welfare status for one or all agents"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            query = "SELECT * FROM v_agent_welfare_status"
            params = []

            if agent_id:
                query += " WHERE agent_id = %s"
                params.append(agent_id)

            cur.execute(query, params)
            results = cur.fetchall()

            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"Error getting welfare status: {e}")
            return []
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_active_alerts(self, severity: str = None, agent_id: int = None) -> List[Dict]:
        """Get active ethics alerts"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            query = "SELECT * FROM v_active_ethics_alerts WHERE 1=1"
            params = []

            if severity:
                query += " AND severity = %s"
                params.append(severity)

            if agent_id:
                query += " AND agent_id = %s"
                params.append(agent_id)

            cur.execute(query, params)
            results = cur.fetchall()

            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"Error getting alerts: {e}")
            return []
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def acknowledge_alert(self, alert_id: int, user_id: int) -> bool:
        """Acknowledge an alert"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE ethics_alerts SET
                    status = 'acknowledged',
                    acknowledged_at = NOW(),
                    acknowledged_by = %s
                WHERE id = %s AND status = 'open'
            """,
                (user_id, alert_id),
            )

            affected = cur.rowcount
            conn.commit()

            return affected > 0

        except Exception as e:
            logger.error(f"Error acknowledging alert: {e}")
            return False
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def resolve_alert(self, alert_id: int, user_id: int, notes: str = None) -> bool:
        """Resolve an alert"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE ethics_alerts SET
                    status = 'resolved',
                    resolved_at = NOW(),
                    resolved_by = %s,
                    resolution_notes = %s
                WHERE id = %s AND status IN ('open', 'acknowledged')
            """,
                (user_id, notes, alert_id),
            )

            affected = cur.rowcount
            conn.commit()

            return affected > 0

        except Exception as e:
            logger.error(f"Error resolving alert: {e}")
            return False
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def generate_weekly_report(self) -> Optional[int]:
        """Generate weekly compliance report"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Calculate period (last 7 days)
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=7)

            # Call database function
            cur.execute(
                """
                SELECT generate_compliance_report('weekly', %s, %s) as report_id
            """,
                (start_date, end_date),
            )

            result = cur.fetchone()
            report_id = result["report_id"] if result else None

            # Add recommendations based on report data
            if report_id:
                cur.execute("SELECT * FROM compliance_reports WHERE id = %s", (report_id,))
                report = cur.fetchone()

                recommendations = []

                if report["stress_incidents"] > 5:
                    recommendations.append("High stress incidents detected. Review workload distribution.")

                if report["energy_incidents"] > 5:
                    recommendations.append("Multiple low energy incidents. Ensure agents are getting adequate rest.")

                if report["constraint_violations"] > 0:
                    recommendations.append(f"{report['constraint_violations']} constraint violations require review.")

                if report["refusals_overridden"] > report["refusals_logged"] * 0.3:
                    recommendations.append("High override rate on refusals. Review task assignment policies.")

                if report["compliance_score"] < 90:
                    recommendations.append("Compliance score below 90%. Immediate attention required.")

                # Update with recommendations
                cur.execute(
                    """
                    UPDATE compliance_reports SET
                        recommendations = %s,
                        status = 'published',
                        published_at = NOW()
                    WHERE id = %s
                """,
                    (recommendations, report_id),
                )

            conn.commit()

            logger.info(f"[ATHENA] Weekly compliance report generated: ID {report_id}")
            return report_id

        except Exception as e:
            logger.error(f"Error generating weekly report: {e}")
            return None
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_compliance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get compliance summary for dashboard"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get alert counts by severity
            cur.execute(
                """
                SELECT
                    severity,
                    COUNT(*) as count
                FROM ethics_alerts
                WHERE created_at > NOW() - INTERVAL '%s days'
                GROUP BY severity
            """,
                (days,),
            )
            alert_counts = {r["severity"]: r["count"] for r in cur.fetchall()}

            # Get recent compliance scores
            cur.execute(
                """
                SELECT compliance_score, period_end
                FROM compliance_reports
                WHERE status = 'published'
                ORDER BY period_end DESC
                LIMIT 4
            """
            )
            recent_scores = cur.fetchall()

            # Get agent welfare distribution
            cur.execute(
                """
                SELECT
                    welfare_status,
                    COUNT(*) as count
                FROM v_agent_welfare_status
                GROUP BY welfare_status
            """
            )
            welfare_dist = {r["welfare_status"]: r["count"] for r in cur.fetchall()}

            # Get monitoring run stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_runs,
                    AVG(agents_checked) as avg_agents,
                    AVG(issues_found) as avg_issues
                FROM ethics_monitoring_runs
                WHERE started_at > NOW() - INTERVAL '%s days'
                AND status = 'completed'
            """,
                (days,),
            )
            run_stats = cur.fetchone()

            return {
                "alert_counts": {
                    "critical": alert_counts.get("critical", 0),
                    "warning": alert_counts.get("warning", 0),
                    "info": alert_counts.get("info", 0),
                },
                "recent_compliance_scores": [dict(s) for s in recent_scores],
                "welfare_distribution": welfare_dist,
                "monitoring_stats": {
                    "total_runs": run_stats["total_runs"] or 0,
                    "avg_agents_per_run": float(run_stats["avg_agents"] or 0),
                    "avg_issues_per_run": float(run_stats["avg_issues"] or 0),
                },
                "period_days": days,
            }

        except Exception as e:
            logger.error(f"Error getting compliance summary: {e}")
            return {}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_athena_status(self) -> Dict[str, Any]:
        """Get ATHENA's current status"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get ATHENA agent info
            cur.execute(
                """
                SELECT id, name, status, last_used
                FROM agents WHERE name = 'ATHENA'
            """
            )
            athena = cur.fetchone()

            if not athena:
                return {
                    "status": "not_deployed",
                    "message": "ATHENA has not been deployed",
                }

            # Get last monitoring run
            cur.execute(
                """
                SELECT started_at, status, agents_checked, issues_found
                FROM ethics_monitoring_runs
                ORDER BY started_at DESC LIMIT 1
            """
            )
            last_run = cur.fetchone()

            # Get open critical alerts
            cur.execute(
                """
                SELECT COUNT(*) as count FROM ethics_alerts
                WHERE severity = 'critical' AND status = 'open'
            """
            )
            critical_count = cur.fetchone()["count"]

            return {
                "status": "active" if athena["status"] == "active" else "inactive",
                "agent_id": athena["id"],
                "name": athena["name"],
                "last_monitoring_run": dict(last_run) if last_run else None,
                "critical_alerts_open": critical_count,
                "message": (
                    "ATHENA is actively monitoring the team"
                    if athena["status"] == "active"
                    else "ATHENA is currently offline"
                ),
            }

        except Exception as e:
            logger.error(f"Error getting ATHENA status: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    # =========================================================================
    # SUB-AGENT GOVERNANCE (Phase 2)
    # =========================================================================

    def check_agent_creation_allowed(self, parent_agent_id: int, conn=None) -> Dict:
        """
        Check if an agent is allowed to create sub-agents.

        Validates:
        1. Agent has a budget with can_create_sub_agents=True
        2. Current sub-agent count < max_sub_agents
        3. Agent generation depth < 3 (prevents recursive spawning)

        Returns dict with 'allowed' bool, 'reason' if blocked, 'remaining' count.
        """
        close_conn = False
        if conn is None:
            conn = get_db()
            close_conn = True

        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check budget
            cur.execute("SELECT * FROM agent_budgets WHERE agent_id = %s", (parent_agent_id,))
            budget = cur.fetchone()

            if not budget or not budget["can_create_sub_agents"]:
                return {
                    "allowed": False,
                    "reason": "Agent not authorized to create sub-agents",
                }

            # Check current sub-agent count
            cur.execute(
                """
                SELECT COUNT(*) as count FROM agents
                WHERE parent_agent_id = %s AND status = 'active'
            """,
                (parent_agent_id,),
            )
            count = cur.fetchone()["count"]

            if count >= budget["max_sub_agents"]:
                return {
                    "allowed": False,
                    "reason": f"Sub-agent limit reached ({count}/{budget['max_sub_agents']})",
                }

            # Check generation depth
            cur.execute("SELECT agent_generation FROM agents WHERE id = %s", (parent_agent_id,))
            gen_row = cur.fetchone()
            if gen_row and gen_row["agent_generation"] is not None and gen_row["agent_generation"] >= 3:
                return {
                    "allowed": False,
                    "reason": "Maximum agent generation depth reached (3)",
                }

            return {
                "allowed": True,
                "remaining": budget["max_sub_agents"] - count,
                "generation": gen_row["agent_generation"] if gen_row else 0,
            }

        except Exception as e:
            logger.error(f"Error checking agent creation permission: {e}")
            return {"allowed": False, "reason": f"Governance check failed: {str(e)}"}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            if close_conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def log_agent_creation_event(
        self,
        parent_agent_id: int,
        child_agent_id: int,
        user_id: int = None,
        reason: str = None,
        source: str = "chat",
        conn=None,
    ) -> bool:
        """Log an agent creation event to the governance audit trail."""
        close_conn = False
        if conn is None:
            conn = get_db()
            close_conn = True

        try:
            cur = conn.cursor()

            # Insert creation event
            cur.execute(
                """
                INSERT INTO agent_creation_events
                    (parent_agent_id, child_agent_id, created_by_user_id,
                     creation_reason, creation_source, is_approved, approved_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
            """,
                (parent_agent_id, child_agent_id, user_id, reason, source),
            )

            # Also log to governance audit
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (event_type, event_category, action, outcome, details, timestamp)
                VALUES ('sub_agent_created', 'autonomy', 'create_agent', 'approved',
                        %s, NOW())
            """,
                (
                    json.dumps(
                        {
                            "parent_agent_id": parent_agent_id,
                            "child_agent_id": child_agent_id,
                            "created_by_user_id": user_id,
                            "reason": reason,
                            "source": source,
                        }
                    ),
                ),
            )

            conn.commit()
            logger.info(f"Agent creation logged: parent={parent_agent_id}, child={child_agent_id}")
            return True

        except Exception as e:
            conn.rollback()
            logger.error(f"Error logging agent creation: {e}")
            return False
        finally:
            try:
                cur.close()
            except Exception:
                pass
            if close_conn:
                try:
                    conn.close()
                except Exception:
                    pass


# Singleton instance
_monitor_instance = None


def get_monitor() -> EthicsMonitor:
    """Get singleton monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = EthicsMonitor()
    return _monitor_instance


# Convenience functions for external use
def run_monitoring_cycle(triggered_by: int = None) -> MonitoringResult:
    """Run a full monitoring cycle"""
    return get_monitor().run_full_monitoring_cycle(triggered_by)


def get_welfare_status(agent_id: int = None) -> List[Dict]:
    """Get agent welfare status"""
    return get_monitor().get_agent_welfare_status(agent_id)


def get_active_alerts(**kwargs) -> List[Dict]:
    """Get active alerts"""
    return get_monitor().get_active_alerts(**kwargs)


def generate_weekly_report() -> Optional[int]:
    """Generate weekly compliance report"""
    return get_monitor().generate_weekly_report()


def get_compliance_summary(days: int = 30) -> Dict[str, Any]:
    """Get compliance summary"""
    return get_monitor().get_compliance_summary(days)


def get_athena_status() -> Dict[str, Any]:
    """Get ATHENA's status"""
    return get_monitor().get_athena_status()
