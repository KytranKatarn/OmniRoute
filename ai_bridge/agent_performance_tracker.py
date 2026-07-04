"""
Agent Performance Tracker
Tracks and analyzes individual agent performance

Author: A.R.C.H.I.E.
Date: 2026-01-01
Purpose: Monitor agent performance, calculate grades, and enable continuous improvement
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    from database import get_db
except ImportError:
    from platform_v2.database import get_db


class AgentPerformanceTracker:
    """Tracks and analyzes agent performance"""

    def __init__(self):
        pass

    def log_agent_action(
        self,
        agent_id: int,
        action_type: str,
        outcome: str,
        proposal_id: Optional[int] = None,
        discussion_id: Optional[int] = None,
        task_description: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        quality_score: Optional[float] = None,
        accuracy_score: Optional[float] = None,
        timeliness_score: Optional[float] = None,
        complexity_level: str = "moderate",
        metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Log an agent action for performance tracking

        Args:
            agent_id: ID of the agent
            action_type: Type of action ('evaluation', 'discussion', 'test', 'deployment', 'code_review')
            outcome: Result ('success', 'failure', 'partial', 'error')
            proposal_id: Related proposal ID (optional)
            discussion_id: Related discussion ID (optional)
            task_description: Description of what was done
            duration_seconds: How long it took
            quality_score: Quality rating 0.0-1.0
            accuracy_score: Accuracy rating 0.0-1.0
            timeliness_score: Timeliness rating 0.0-1.0
            complexity_level: Task complexity ('simple', 'moderate', 'complex', 'expert')
            metadata: Additional data

        Returns:
            True if logged successfully
        """
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO agent_performance_logs (
                        agent_id,
                        action_type,
                        proposal_id,
                        discussion_id,
                        task_description,
                        outcome,
                        duration_seconds,
                        quality_score,
                        accuracy_score,
                        timeliness_score,
                        complexity_level,
                        metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        agent_id,
                        action_type,
                        proposal_id,
                        discussion_id,
                        task_description,
                        outcome,
                        duration_seconds,
                        quality_score,
                        accuracy_score,
                        timeliness_score,
                        complexity_level,
                        str(metadata).replace("'", '"') if metadata else None,
                    ),
                )

                conn.commit()

                print(f"✅ Logged action for agent #{agent_id}: {action_type} ({outcome})")
                return True
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error logging agent action: {e}")
            import traceback

            traceback.print_exc()
            return False

    def calculate_agent_metrics(self, agent_id: int) -> Dict:
        """
        Calculate comprehensive metrics for an agent

        Args:
            agent_id: ID of the agent

        Returns:
            Dictionary with calculated metrics
        """
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                # Get all performance logs for this agent
                cur.execute(
                    """
                    SELECT
                        action_type,
                        outcome,
                        duration_seconds,
                        quality_score,
                        accuracy_score,
                        timeliness_score,
                        complexity_level,
                        created_at
                    FROM agent_performance_logs
                    WHERE agent_id = %s
                    ORDER BY created_at DESC
                """,
                    (agent_id,),
                )

                logs = cur.fetchall()

                if not logs:
                    # No logs yet, return default metrics
                    return {
                        "total_tasks_completed": 0,
                        "total_tasks_failed": 0,
                        "success_rate": 0.0,
                        "avg_quality_score": 0.75,
                        "overall_score": 75.0,
                        "overall_grade": "C",
                    }

                # Calculate basic metrics
                total_tasks = len(logs)
                successful_tasks = sum(1 for log in logs if log[1] == "success")
                failed_tasks = sum(1 for log in logs if log[1] == "failure")
                success_rate = (successful_tasks / total_tasks) if total_tasks > 0 else 0.0

                # Calculate average scores (only from logs that have scores)
                quality_scores = [float(log[3]) for log in logs if log[3] is not None]
                accuracy_scores = [float(log[4]) for log in logs if log[4] is not None]
                timeliness_scores = [float(log[5]) for log in logs if log[5] is not None]

                avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.75
                avg_accuracy = sum(accuracy_scores) / len(accuracy_scores) if accuracy_scores else 0.75
                avg_timeliness = sum(timeliness_scores) / len(timeliness_scores) if timeliness_scores else 0.75

                # Calculate tasks in last 30 days
                thirty_days_ago = datetime.now() - timedelta(days=30)
                recent_tasks = sum(1 for log in logs if log[7] >= thirty_days_ago)

                # Calculate average duration
                durations = [int(log[2]) for log in logs if log[2] is not None]
                avg_duration = int(sum(durations) / len(durations)) if durations else 0

                # Get evaluation-specific metrics
                cur.execute(
                    """
                    SELECT COUNT(*) as evaluations_given
                    FROM proposal_evaluations
                    WHERE agent_id = %s
                """,
                    (agent_id,),
                )
                evaluations_given = cur.fetchone()[0] or 0

                # Calculate consensus agreement rate
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_evaluations,
                        SUM(CASE
                            WHEN pe.recommendation = tc.final_recommendation THEN 1
                            ELSE 0
                        END) as agreed_with_consensus
                    FROM proposal_evaluations pe
                    JOIN team_consensus tc ON pe.proposal_id = tc.proposal_id
                    WHERE pe.agent_id = %s
                """,
                    (agent_id,),
                )

                consensus_data = cur.fetchone()
                total_evals = consensus_data[0] or 0
                agreed_evals = consensus_data[1] or 0
                consensus_agreement_rate = (agreed_evals / total_evals) if total_evals > 0 else 0.0

                # Get proposal success metrics
                cur.execute(
                    """
                    SELECT
                        COUNT(CASE WHEN pe.recommendation = 'approve' THEN 1 END) as approved,
                        COUNT(CASE WHEN pe.recommendation = 'reject' THEN 1 END) as rejected,
                        COUNT(CASE WHEN p.status = 'implemented' AND pe.recommendation = 'approve' THEN 1 END) as successful_implementations,
                        COUNT(CASE WHEN p.status = 'failed' AND pe.recommendation = 'approve' THEN 1 END) as failed_implementations
                    FROM proposal_evaluations pe
                    JOIN improvement_proposals p ON pe.proposal_id = p.id
                    WHERE pe.agent_id = %s
                """,
                    (agent_id,),
                )

                proposal_data = cur.fetchone()
                proposals_approved = proposal_data[0] or 0
                proposals_rejected = proposal_data[1] or 0
                proposals_implemented = proposal_data[2] or 0
                proposals_failed = proposal_data[3] or 0

                proposal_success_rate = (
                    (proposals_implemented / (proposals_implemented + proposals_failed))
                    if (proposals_implemented + proposals_failed) > 0
                    else 0.0
                )

                # Calculate overall score (0-100)
                # Weighted formula:
                # - Success rate: 30%
                # - Quality score: 25%
                # - Accuracy score: 20%
                # - Consensus agreement: 15%
                # - Timeliness: 10%
                overall_score = (
                    (success_rate * 30)
                    + (avg_quality * 25)
                    + (avg_accuracy * 20)
                    + (consensus_agreement_rate * 15)
                    + (avg_timeliness * 10)
                )

                # Determine grade
                if overall_score >= 97:
                    grade = "A+"
                elif overall_score >= 93:
                    grade = "A"
                elif overall_score >= 90:
                    grade = "A-"
                elif overall_score >= 87:
                    grade = "B+"
                elif overall_score >= 83:
                    grade = "B"
                elif overall_score >= 80:
                    grade = "B-"
                elif overall_score >= 77:
                    grade = "C+"
                elif overall_score >= 73:
                    grade = "C"
                elif overall_score >= 70:
                    grade = "C-"
                elif overall_score >= 60:
                    grade = "D"
                else:
                    grade = "F"

                # Determine performance trend (compare last 10 tasks vs previous 10)
                if len(logs) >= 20:
                    recent_success = sum(1 for log in logs[:10] if log[1] == "success") / 10
                    older_success = sum(1 for log in logs[10:20] if log[1] == "success") / 10

                    if recent_success > older_success + 0.1:
                        trend = "improving"
                    elif recent_success < older_success - 0.1:
                        trend = "declining"
                    else:
                        trend = "stable"
                else:
                    trend = "stable"

                # Determine proficiency level
                if overall_score >= 95:
                    proficiency = "master"
                elif overall_score >= 85:
                    proficiency = "expert"
                elif overall_score >= 75:
                    proficiency = "advanced"
                elif overall_score >= 65:
                    proficiency = "intermediate"
                else:
                    proficiency = "novice"

                metrics = {
                    "total_tasks_completed": total_tasks,
                    "total_tasks_failed": failed_tasks,
                    "tasks_last_30_days": recent_tasks,
                    "avg_task_duration_seconds": avg_duration,
                    "avg_quality_score": round(avg_quality, 2),
                    "avg_accuracy_score": round(avg_accuracy, 2),
                    "avg_timeliness_score": round(avg_timeliness, 2),
                    "evaluations_given": evaluations_given,
                    "consensus_agreement_rate": round(consensus_agreement_rate, 2),
                    "proposals_approved": proposals_approved,
                    "proposals_rejected": proposals_rejected,
                    "proposals_implemented_successfully": proposals_implemented,
                    "proposals_failed_in_production": proposals_failed,
                    "success_rate": round(success_rate, 2),
                    "overall_score": round(overall_score, 2),
                    "overall_grade": grade,
                    "performance_trend": trend,
                    "proficiency_level": proficiency,
                }

                return metrics
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error calculating agent metrics: {e}")
            import traceback

            traceback.print_exc()
            return {}

    def update_agent_metrics(self, agent_id: int) -> bool:
        """
        Update agent_performance_metrics table with latest calculations

        Args:
            agent_id: ID of the agent

        Returns:
            True if updated successfully
        """
        try:
            metrics = self.calculate_agent_metrics(agent_id)

            if not metrics:
                return False

            conn = get_db()
            try:
                cur = conn.cursor()

                # Get specialization areas (categories where agent excels)
                cur.execute(
                    """
                    SELECT
                        p.category,
                        COUNT(*) as count,
                        AVG(CASE WHEN p.status = 'implemented' THEN 1.0 ELSE 0.0 END) as success_rate
                    FROM proposal_evaluations pe
                    JOIN improvement_proposals p ON pe.proposal_id = p.id
                    WHERE pe.agent_id = %s
                    AND pe.recommendation = 'approve'
                    GROUP BY p.category
                    HAVING AVG(CASE WHEN p.status = 'implemented' THEN 1.0 ELSE 0.0 END) > 0.7
                    AND COUNT(*) >= 3
                    ORDER BY success_rate DESC, count DESC
                    LIMIT 5
                """,
                    (agent_id,),
                )

                specializations = [row[0] for row in cur.fetchall()]

                # Update or insert metrics
                cur.execute(
                    """
                    INSERT INTO agent_performance_metrics (
                        agent_id,
                        overall_grade,
                        overall_score,
                        performance_trend,
                        total_tasks_completed,
                        total_tasks_failed,
                        tasks_last_30_days,
                        avg_task_duration_seconds,
                        avg_quality_score,
                        avg_accuracy_score,
                        avg_timeliness_score,
                        evaluations_given,
                        consensus_agreement_rate,
                        proposals_approved,
                        proposals_rejected,
                        proposals_implemented_successfully,
                        proposals_failed_in_production,
                        success_rate,
                        proficiency_level,
                        specialization_areas,
                        last_updated,
                        last_task_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                    ON CONFLICT (agent_id) DO UPDATE SET
                        overall_grade = EXCLUDED.overall_grade,
                        overall_score = EXCLUDED.overall_score,
                        performance_trend = EXCLUDED.performance_trend,
                        total_tasks_completed = EXCLUDED.total_tasks_completed,
                        total_tasks_failed = EXCLUDED.total_tasks_failed,
                        tasks_last_30_days = EXCLUDED.tasks_last_30_days,
                        avg_task_duration_seconds = EXCLUDED.avg_task_duration_seconds,
                        avg_quality_score = EXCLUDED.avg_quality_score,
                        avg_accuracy_score = EXCLUDED.avg_accuracy_score,
                        avg_timeliness_score = EXCLUDED.avg_timeliness_score,
                        evaluations_given = EXCLUDED.evaluations_given,
                        consensus_agreement_rate = EXCLUDED.consensus_agreement_rate,
                        proposals_approved = EXCLUDED.proposals_approved,
                        proposals_rejected = EXCLUDED.proposals_rejected,
                        proposals_implemented_successfully = EXCLUDED.proposals_implemented_successfully,
                        proposals_failed_in_production = EXCLUDED.proposals_failed_in_production,
                        success_rate = EXCLUDED.success_rate,
                        proficiency_level = EXCLUDED.proficiency_level,
                        specialization_areas = EXCLUDED.specialization_areas,
                        last_updated = NOW(),
                        last_task_at = NOW()
                """,
                    (
                        agent_id,
                        metrics["overall_grade"],
                        metrics["overall_score"],
                        metrics["performance_trend"],
                        metrics["total_tasks_completed"],
                        metrics["total_tasks_failed"],
                        metrics["tasks_last_30_days"],
                        metrics["avg_task_duration_seconds"],
                        metrics["avg_quality_score"],
                        metrics["avg_accuracy_score"],
                        metrics["avg_timeliness_score"],
                        metrics["evaluations_given"],
                        metrics["consensus_agreement_rate"],
                        metrics["proposals_approved"],
                        metrics["proposals_rejected"],
                        metrics["proposals_implemented_successfully"],
                        metrics["proposals_failed_in_production"],
                        metrics["success_rate"],
                        metrics["proficiency_level"],
                        specializations,
                    ),
                )

                conn.commit()

                print(
                    f"✅ Updated metrics for agent #{agent_id}: Grade {metrics['overall_grade']} (Score: {metrics['overall_score']})"
                )
                return True
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error updating agent metrics: {e}")
            import traceback

            traceback.print_exc()
            return False

    def get_agent_performance(self, agent_id: int) -> Optional[Dict]:
        """Get current performance data for an agent"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT * FROM agent_performance_summary
                    WHERE agent_id = %s
                """,
                    (agent_id,),
                )

                row = cur.fetchone()

                if not row:
                    return None

                columns = [
                    "agent_id",
                    "agent_name",
                    "department",
                    "overall_grade",
                    "overall_score",
                    "performance_trend",
                    "total_tasks_completed",
                    "tasks_last_30_days",
                    "success_rate",
                    "avg_quality_score",
                    "consensus_agreement_rate",
                    "proficiency_level",
                    "specialization_areas",
                    "last_task_at",
                    "actionable_insights_count",
                ]

                return dict(zip(columns, row))
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error getting agent performance: {e}")
            return None

    def get_performance_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get top performing agents"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT * FROM agent_performance_leaderboard
                    LIMIT %s
                """,
                    (limit,),
                )

                rows = cur.fetchall()

                columns = [
                    "agent_id",
                    "agent_name",
                    "department",
                    "tier",
                    "worker_type",
                    "current_grade",
                    "performance_score",
                    "total_tasks_completed",
                    "success_rate",
                    "overall_score",
                    "performance_trend",
                    "proficiency_level",
                    "avg_quality_score",
                    "consensus_agreement_rate",
                    "overall_rank",
                    "department_rank",
                ]

                return [dict(zip(columns, row)) for row in rows]
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"Error getting leaderboard: {e}")
            import traceback

            traceback.print_exc()
            return []


# Convenience functions
def log_agent_action(agent_id: int, action_type: str, outcome: str, **kwargs) -> bool:
    """Log an agent action"""
    tracker = AgentPerformanceTracker()
    return tracker.log_agent_action(agent_id, action_type, outcome, **kwargs)


def update_agent_performance(agent_id: int) -> bool:
    """Update agent performance metrics"""
    tracker = AgentPerformanceTracker()
    return tracker.update_agent_metrics(agent_id)


def get_agent_performance(agent_id: int) -> Optional[Dict]:
    """Get agent performance data"""
    tracker = AgentPerformanceTracker()
    return tracker.get_agent_performance(agent_id)


def get_top_performers(limit: int = 10) -> List[Dict]:
    """Get top performing agents"""
    tracker = AgentPerformanceTracker()
    return tracker.get_performance_leaderboard(limit)


if __name__ == "__main__":
    # Test the performance tracker
    print("🧪 Testing Agent Performance Tracker...")

    tracker = AgentPerformanceTracker()

    # Get leaderboard
    leaderboard = tracker.get_performance_leaderboard(limit=5)
    print(f"\nTop 5 Agents:")
    for agent in leaderboard:
        print(
            f"  #{agent['overall_rank']} {agent['agent_name']} - Grade: {agent['current_grade']} (Score: {agent['performance_score']})"
        )
