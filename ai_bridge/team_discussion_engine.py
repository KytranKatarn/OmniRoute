"""
Team Discussion Engine
Manages multi-agent collaborative discussions on improvement proposals

Author: A.R.C.H.I.E.
Date: 2026-01-01
Purpose: Enable agents to collaborate, share insights, and reach consensus on proposals
"""

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_v2.database import get_db


class TeamDiscussionEngine:
    """Orchestrates multi-agent discussions and consensus building"""

    def __init__(self):
        self.archie_id = self._get_archie_agent_id()

    def _get_archie_agent_id(self) -> Optional[int]:
        """Get A.R.C.H.I.E.'s agent ID from the agents table"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id FROM agents
                WHERE name = 'A.R.C.H.I.E.'
                AND status = 'active'
                LIMIT 1
            """
            )
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            print(f"Error getting A.R.C.H.I.E. agent ID: {e}")
            return None

    def start_discussion(self, proposal_id: int, topic: str, description: Optional[str] = None) -> Optional[int]:
        """
        Start a new discussion session for a proposal

        Args:
            proposal_id: ID of the improvement proposal
            topic: Brief topic/title of the discussion
            description: Detailed description of what to discuss

        Returns:
            Discussion ID if successful, None otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Create discussion session with A.R.C.H.I.E. as facilitator
            cur.execute(
                """
                INSERT INTO agent_discussions (
                    proposal_id,
                    topic,
                    description,
                    facilitator_id,
                    status
                ) VALUES (%s, %s, %s, %s, 'active')
                RETURNING id
            """,
                (proposal_id, topic, description, self.archie_id),
            )

            discussion_id = cur.fetchone()[0]

            # Update proposal to link to discussion
            cur.execute(
                """
                UPDATE improvement_proposals
                SET discussion_id = %s
                WHERE id = %s
            """,
                (discussion_id, proposal_id),
            )

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Discussion #{discussion_id} started for proposal #{proposal_id}")
            return discussion_id

        except Exception as e:
            print(f"Error starting discussion: {e}")
            import traceback

            traceback.print_exc()
            return None

    def start_adhoc_discussion(
        self,
        topic: str,
        stations: List[str] = None,
        user_id: int = None,
        description: str = None,
    ) -> Optional[int]:
        """
        Start an ad-hoc discussion session (not linked to a proposal)

        Phase 63: Enables multi-agent discussions for general queries,
        not just improvement proposals.

        Args:
            topic: Brief topic/title of the discussion
            stations: List of Bridge stations to involve (e.g., ['ENGINEERING', 'SECURITY'])
            user_id: User who initiated the discussion
            description: Detailed description of what to discuss

        Returns:
            Discussion ID if successful, None otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Build metadata for ad-hoc discussion
            metadata = {
                "discussion_type": "adhoc",
                "stations": stations or [],
                "initiated_by_user": user_id,
            }

            # Create discussion session without proposal_id
            cur.execute(
                """
                INSERT INTO agent_discussions (
                    proposal_id,
                    topic,
                    description,
                    facilitator_id,
                    status,
                    metadata
                ) VALUES (NULL, %s, %s, %s, 'active', %s)
                RETURNING id
            """,
                (
                    topic,
                    description or f"Ad-hoc discussion: {topic}",
                    self.archie_id,
                    json.dumps(metadata),
                ),
            )

            discussion_id = cur.fetchone()[0]

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Ad-hoc discussion #{discussion_id} started: {topic[:50]}...")
            return discussion_id

        except Exception as e:
            print(f"Error starting ad-hoc discussion: {e}")
            import traceback

            traceback.print_exc()
            return None

    def assign_agents_to_discussion(self, discussion_id: int, agent_ids: List[int]) -> bool:
        """
        Assign specialist agents to a discussion

        Args:
            discussion_id: ID of the discussion session
            agent_ids: List of agent IDs to participate

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Get proposal_id from discussion
            cur.execute(
                """
                SELECT proposal_id FROM agent_discussions WHERE id = %s
            """,
                (discussion_id,),
            )
            result = cur.fetchone()

            if not result:
                print(f"Discussion #{discussion_id} not found")
                return False

            proposal_id = result[0]

            # Assign each agent to both the discussion and the team assignments
            for agent_id in agent_ids:
                # Check if already assigned
                cur.execute(
                    """
                    SELECT id FROM improvement_team_assignments
                    WHERE proposal_id = %s AND agent_id = %s
                """,
                    (proposal_id, agent_id),
                )

                if not cur.fetchone():
                    # Assign to team
                    cur.execute(
                        """
                        INSERT INTO improvement_team_assignments (
                            proposal_id,
                            agent_id,
                            role,
                            status
                        ) VALUES (%s, %s, 'reviewer', 'assigned')
                    """,
                        (proposal_id, agent_id),
                    )

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Assigned {len(agent_ids)} agents to discussion #{discussion_id}")
            return True

        except Exception as e:
            print(f"Error assigning agents: {e}")
            import traceback

            traceback.print_exc()
            return False

    def agent_contribute(
        self,
        discussion_id: int,
        agent_id: int,
        message: str,
        message_type: str = "analysis",
        confidence_score: float = 0.8,
        supporting_data: Optional[Dict] = None,
    ) -> bool:
        """
        Record an agent's contribution to the discussion

        Args:
            discussion_id: ID of the discussion session
            agent_id: ID of the contributing agent
            message: The agent's message/contribution
            message_type: Type of message ('analysis', 'recommendation', 'concern', 'approval', 'question')
            confidence_score: Agent's confidence in their input (0.0 to 1.0)
            supporting_data: Additional data (code analysis, metrics, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Insert contribution
            cur.execute(
                """
                INSERT INTO agent_discussion_messages (
                    discussion_id,
                    agent_id,
                    message_type,
                    message,
                    confidence_score,
                    supporting_data
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    discussion_id,
                    agent_id,
                    message_type,
                    message,
                    confidence_score,
                    supporting_data,
                ),
            )

            message_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Agent #{agent_id} contributed to discussion #{discussion_id} (message #{message_id})")
            return True

        except Exception as e:
            print(f"Error recording contribution: {e}")
            import traceback

            traceback.print_exc()
            return False

    def create_agent_evaluation(
        self,
        proposal_id: int,
        discussion_id: int,
        agent_id: int,
        recommendation: str,
        confidence_level: float,
        risk_assessment: str,
        estimated_effort: str,
        technical_notes: str,
        manager_summary: str,
        concerns: List[str] = None,
        benefits: List[str] = None,
        role: str = "reviewer",
    ) -> bool:
        """
        Create a formal evaluation from an agent

        Args:
            proposal_id: ID of the proposal being evaluated
            discussion_id: ID of the discussion session
            agent_id: ID of the evaluating agent
            recommendation: 'approve', 'reject', 'needs_changes', 'needs_testing'
            confidence_level: Agent's confidence (0.0 to 1.0)
            risk_assessment: 'low', 'medium', 'high', 'critical'
            estimated_effort: Time estimate ('1-2h', '2-4h', '1-2d', etc.)
            technical_notes: Detailed technical analysis
            manager_summary: Non-technical summary for management
            concerns: List of concern strings
            benefits: List of benefit strings
            role: Agent's role in evaluation ('lead', 'reviewer', 'specialist')

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Insert evaluation
            cur.execute(
                """
                INSERT INTO proposal_evaluations (
                    proposal_id,
                    discussion_id,
                    agent_id,
                    role,
                    recommendation,
                    confidence_level,
                    risk_assessment,
                    estimated_effort,
                    technical_notes,
                    manager_summary,
                    concerns,
                    benefits
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id, agent_id)
                DO UPDATE SET
                    recommendation = EXCLUDED.recommendation,
                    confidence_level = EXCLUDED.confidence_level,
                    risk_assessment = EXCLUDED.risk_assessment,
                    estimated_effort = EXCLUDED.estimated_effort,
                    technical_notes = EXCLUDED.technical_notes,
                    manager_summary = EXCLUDED.manager_summary,
                    concerns = EXCLUDED.concerns,
                    benefits = EXCLUDED.benefits,
                    created_at = NOW()
                RETURNING id
            """,
                (
                    proposal_id,
                    discussion_id,
                    agent_id,
                    role,
                    recommendation,
                    confidence_level,
                    risk_assessment,
                    estimated_effort,
                    technical_notes,
                    manager_summary,
                    concerns or [],
                    benefits or [],
                ),
            )

            eval_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Agent #{agent_id} created evaluation #{eval_id} for proposal #{proposal_id}")
            return True

        except Exception as e:
            print(f"Error creating evaluation: {e}")
            import traceback

            traceback.print_exc()
            return False

    def calculate_consensus(self, discussion_id: int) -> Tuple[float, Dict]:
        """
        Calculate consensus score and statistics for a discussion

        Args:
            discussion_id: ID of the discussion session

        Returns:
            Tuple of (consensus_score, statistics_dict)
            consensus_score: 0.0 to 1.0 (level of agreement)
            statistics_dict: Contains approval counts, recommendations, etc.
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Get proposal_id
            cur.execute(
                "SELECT proposal_id FROM agent_discussions WHERE id = %s",
                (discussion_id,),
            )
            result = cur.fetchone()
            if not result:
                return 0.0, {}

            proposal_id = result[0]

            # Get all evaluations for this proposal
            cur.execute(
                """
                SELECT
                    recommendation,
                    confidence_level,
                    risk_assessment,
                    estimated_effort,
                    concerns,
                    benefits,
                    agent_id
                FROM proposal_evaluations
                WHERE proposal_id = %s AND discussion_id = %s
            """,
                (proposal_id, discussion_id),
            )

            evaluations = cur.fetchall()
            cur.close()
            conn.close()

            if not evaluations:
                return 0.0, {"error": "No evaluations found"}

            # Count recommendations
            approval_count = sum(1 for e in evaluations if e[0] == "approve")
            rejection_count = sum(1 for e in evaluations if e[0] == "reject")
            needs_changes_count = sum(1 for e in evaluations if e[0] == "needs_changes")
            needs_testing_count = sum(1 for e in evaluations if e[0] == "needs_testing")
            total_count = len(evaluations)

            # Calculate consensus score
            # High consensus = high percentage of same recommendation
            max_same_recommendation = max(
                approval_count,
                rejection_count,
                needs_changes_count,
                needs_testing_count,
            )
            consensus_score = max_same_recommendation / total_count if total_count > 0 else 0.0

            # Average confidence
            avg_confidence = sum(e[1] for e in evaluations) / total_count if total_count > 0 else 0.0

            # Aggregate concerns and benefits
            all_concerns = []
            all_benefits = []
            participating_agents = []

            for eval_data in evaluations:
                concerns = eval_data[4] or []
                benefits = eval_data[5] or []
                agent_id = eval_data[6]

                all_concerns.extend(concerns)
                all_benefits.extend(benefits)
                participating_agents.append(agent_id)

            # Risk assessment (take the highest risk level)
            risk_levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            risk_assessments = [e[2] for e in evaluations if e[2]]
            highest_risk = max(risk_assessments, key=lambda x: risk_levels.get(x, 0)) if risk_assessments else "medium"

            # Determine final recommendation
            if approval_count >= total_count * 0.7:
                final_recommendation = "approved"
            elif rejection_count >= total_count * 0.5:
                final_recommendation = "rejected"
            elif needs_changes_count + needs_testing_count >= total_count * 0.5:
                final_recommendation = "needs_revision"
            else:
                final_recommendation = "needs_revision"  # Default to cautious

            stats = {
                "consensus_score": round(consensus_score, 2),
                "final_recommendation": final_recommendation,
                "approval_count": approval_count,
                "rejection_count": rejection_count,
                "needs_changes_count": needs_changes_count,
                "needs_testing_count": needs_testing_count,
                "total_evaluations": total_count,
                "avg_confidence": round(avg_confidence, 2),
                "highest_risk": highest_risk,
                "all_concerns": list(set(all_concerns)),  # Remove duplicates
                "all_benefits": list(set(all_benefits)),
                "participating_agents": participating_agents,
            }

            print(
                f"✅ Consensus calculated for discussion #{discussion_id}: {consensus_score:.2f} ({final_recommendation})"
            )
            return consensus_score, stats

        except Exception as e:
            print(f"Error calculating consensus: {e}")
            import traceback

            traceback.print_exc()
            return 0.0, {"error": str(e)}

    def create_team_consensus(
        self,
        proposal_id: int,
        discussion_id: int,
        implementation_plan: Optional[str] = None,
        priority_recommendation: Optional[str] = None,
    ) -> Optional[int]:
        """
        Create a formal team consensus record

        Args:
            proposal_id: ID of the proposal
            discussion_id: ID of the discussion session
            implementation_plan: Detailed implementation plan (optional)
            priority_recommendation: Priority level (optional)

        Returns:
            Consensus ID if successful, None otherwise
        """
        try:
            # Calculate consensus first
            consensus_score, stats = self.calculate_consensus(discussion_id)

            if "error" in stats:
                print(f"Cannot create consensus: {stats['error']}")
                return None

            conn = get_db()
            cur = conn.cursor()

            # Create consensus record
            cur.execute(
                """
                INSERT INTO team_consensus (
                    proposal_id,
                    discussion_id,
                    final_recommendation,
                    consensus_score,
                    participating_agents,
                    approval_count,
                    rejection_count,
                    abstain_count,
                    key_benefits,
                    key_risks,
                    implementation_plan,
                    estimated_total_effort,
                    priority_recommendation,
                    created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    proposal_id,
                    discussion_id,
                    stats["final_recommendation"],
                    consensus_score,
                    stats["participating_agents"],
                    stats["approval_count"],
                    stats["rejection_count"],
                    0,  # abstain_count (not currently tracked)
                    stats["all_benefits"][:10],  # Top 10 benefits
                    stats["all_concerns"][:10],  # Top 10 concerns
                    implementation_plan,
                    "TBD",  # estimated_total_effort (can be calculated from evaluations)
                    priority_recommendation or "medium",
                    self.archie_id,
                ),
            )

            consensus_id = cur.fetchone()[0]

            # Update proposal to link consensus
            cur.execute(
                """
                UPDATE improvement_proposals
                SET consensus_id = %s,
                    team_recommendation = %s
                WHERE id = %s
            """,
                (consensus_id, stats["final_recommendation"], proposal_id),
            )

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Team consensus #{consensus_id} created for proposal #{proposal_id}")
            return consensus_id

        except Exception as e:
            print(f"Error creating team consensus: {e}")
            import traceback

            traceback.print_exc()
            return None

    def close_discussion(self, discussion_id: int, consensus_reached: bool = True) -> bool:
        """
        Close a discussion session

        Args:
            discussion_id: ID of the discussion to close
            consensus_reached: Whether consensus was reached

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Calculate final consensus score
            consensus_score, _ = self.calculate_consensus(discussion_id)

            # Update discussion status
            cur.execute(
                """
                UPDATE agent_discussions
                SET status = %s,
                    ended_at = NOW(),
                    consensus_reached = %s,
                    consensus_score = %s
                WHERE id = %s
            """,
                (
                    "consensus_reached" if consensus_reached else "closed",
                    consensus_reached,
                    consensus_score,
                    discussion_id,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            print(
                f"✅ Discussion #{discussion_id} closed (consensus: {consensus_reached}, score: {consensus_score:.2f})"
            )
            return True

        except Exception as e:
            print(f"Error closing discussion: {e}")
            import traceback

            traceback.print_exc()
            return False

    def get_discussion_summary(self, discussion_id: int) -> Optional[Dict]:
        """
        Get a complete summary of a discussion

        Args:
            discussion_id: ID of the discussion

        Returns:
            Dictionary with discussion details, messages, evaluations, and consensus
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Get discussion details
            cur.execute(
                """
                SELECT
                    d.id,
                    d.proposal_id,
                    d.topic,
                    d.description,
                    d.status,
                    d.started_at::text,
                    d.ended_at::text,
                    d.consensus_reached,
                    d.consensus_score,
                    p.title as proposal_title,
                    p.description as proposal_description
                FROM agent_discussions d
                JOIN improvement_proposals p ON d.proposal_id = p.id
                WHERE d.id = %s
            """,
                (discussion_id,),
            )

            discussion = cur.fetchone()
            if not discussion:
                return None

            # Get messages
            cur.execute(
                """
                SELECT
                    m.id,
                    m.agent_id,
                    COALESCE(a.first_name || ' ' || a.last_name, a.name) as agent_name,
                    m.message_type,
                    m.message,
                    m.confidence_score,
                    m.created_at::text
                FROM agent_discussion_messages m
                JOIN agents a ON m.agent_id = a.id
                WHERE m.discussion_id = %s
                ORDER BY m.created_at ASC
            """,
                (discussion_id,),
            )

            messages = cur.fetchall()

            # Get evaluations
            cur.execute(
                """
                SELECT
                    e.id,
                    e.agent_id,
                    COALESCE(a.first_name || ' ' || a.last_name, a.name) as agent_name,
                    e.recommendation,
                    e.confidence_level,
                    e.risk_assessment,
                    e.technical_notes,
                    e.manager_summary,
                    e.concerns,
                    e.benefits
                FROM proposal_evaluations e
                JOIN agents a ON e.agent_id = a.id
                WHERE e.discussion_id = %s
            """,
                (discussion_id,),
            )

            evaluations = cur.fetchall()

            # Get consensus if exists
            cur.execute(
                """
                SELECT
                    id,
                    final_recommendation,
                    consensus_score,
                    approval_count,
                    rejection_count,
                    key_benefits,
                    key_risks,
                    created_at::text
                FROM team_consensus
                WHERE discussion_id = %s
            """,
                (discussion_id,),
            )

            consensus = cur.fetchone()

            cur.close()
            conn.close()

            summary = {
                "discussion": {
                    "id": discussion[0],
                    "proposal_id": discussion[1],
                    "topic": discussion[2],
                    "description": discussion[3],
                    "status": discussion[4],
                    "started_at": discussion[5],
                    "ended_at": discussion[6],
                    "consensus_reached": discussion[7],
                    "consensus_score": float(discussion[8]) if discussion[8] else 0.0,
                    "proposal_title": discussion[9],
                    "proposal_description": discussion[10],
                },
                "messages": [
                    {
                        "id": m[0],
                        "agent_id": m[1],
                        "agent_name": m[2],
                        "type": m[3],
                        "message": m[4],
                        "confidence": float(m[5]) if m[5] else 0.0,
                        "created_at": m[6],
                    }
                    for m in messages
                ],
                "evaluations": [
                    {
                        "id": e[0],
                        "agent_id": e[1],
                        "agent_name": e[2],
                        "recommendation": e[3],
                        "confidence": float(e[4]) if e[4] else 0.0,
                        "risk": e[5],
                        "technical_notes": e[6],
                        "manager_summary": e[7],
                        "concerns": e[8] or [],
                        "benefits": e[9] or [],
                    }
                    for e in evaluations
                ],
                "consensus": (
                    {
                        "id": consensus[0],
                        "final_recommendation": consensus[1],
                        "score": float(consensus[2]) if consensus[2] else 0.0,
                        "approvals": consensus[3],
                        "rejections": consensus[4],
                        "benefits": consensus[5] or [],
                        "risks": consensus[6] or [],
                        "created_at": consensus[7],
                    }
                    if consensus
                    else None
                ),
            }

            return summary

        except Exception as e:
            print(f"Error getting discussion summary: {e}")
            import traceback

            traceback.print_exc()
            return None


# Convenience functions for easy import
def start_team_discussion(proposal_id: int, topic: str, description: str = None) -> Optional[int]:
    """Start a new team discussion for a proposal"""
    engine = TeamDiscussionEngine()
    return engine.start_discussion(proposal_id, topic, description)


def add_agent_to_discussion(discussion_id: int, agent_id: int, message: str, message_type: str = "analysis") -> bool:
    """Add an agent's contribution to a discussion"""
    engine = TeamDiscussionEngine()
    return engine.agent_contribute(discussion_id, agent_id, message, message_type)


def finalize_team_consensus(proposal_id: int, discussion_id: int) -> Optional[int]:
    """Create final team consensus for a proposal"""
    engine = TeamDiscussionEngine()
    consensus_id = engine.create_team_consensus(proposal_id, discussion_id)
    if consensus_id:
        engine.close_discussion(discussion_id, consensus_reached=True)
    return consensus_id


if __name__ == "__main__":
    # Test the discussion engine
    print("🧪 Testing Team Discussion Engine...")

    engine = TeamDiscussionEngine()
    print(f"A.R.C.H.I.E. Agent ID: {engine.archie_id}")

    # Example: Create a test discussion
    # discussion_id = engine.start_discussion(
    #     proposal_id=1,
    #     topic="Evaluate database optimization proposal",
    #     description="Team evaluation of proposed database indexing improvements"
    # )
    # print(f"Test discussion created: #{discussion_id}")
