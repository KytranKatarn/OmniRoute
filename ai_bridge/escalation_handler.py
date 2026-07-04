"""
Escalation Handler for A.R.C.H.I.E.
Intelligent escalation routing based on skills and experience

Features:
- Skill-based escalation chains
- Multi-level escalation (agent → senior → admin)
- Escalation tracking and notifications
- Automatic reassignment
"""

import os
from db import _get_db_password
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Optional
import json


class EscalationHandler:
    """
    Manages escalation of improvement proposals to more experienced agents.

    Escalation Chain:
    Level 1: Assigned agent
    Level 2: Senior agent (from can_escalate_to in agent_skills)
    Level 3: Department manager
    Level 4: Admin

    Escalation Triggers:
    - Stuck in status too long
    - Repeated failures
    - Agent requests escalation
    - Complexity exceeds agent capability
    """

    def __init__(self):
        pass

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def escalate_proposal(
        self,
        proposal_id: int,
        reason: str,
        escalated_by_user_id: int = None,
        auto_triggered: bool = False,
    ) -> Dict:
        """
        Escalate a proposal to higher level.

        Args:
            proposal_id: Proposal to escalate
            reason: Reason for escalation
            escalated_by_user_id: User who triggered escalation
            auto_triggered: Whether automatically triggered

        Returns:
            {
                'success': True,
                'escalation_level': 2,
                'escalated_to': 'Senior Engineer',
                'new_team': [...]
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            try:
                # Get proposal details
                cur.execute(
                    """
                    SELECT * FROM improvement_proposals
                    WHERE id = %s
                """,
                    (proposal_id,),
                )

                proposal = cur.fetchone()

                if not proposal:
                    return {"success": False, "error": f"Proposal {proposal_id} not found"}

                # Determine escalation level
                current_escalation = proposal.get("metadata", {}).get("escalation_level", 0)
                next_escalation_level = current_escalation + 1

                # Find escalation target
                escalation_target = self._find_escalation_target(
                    proposal_id, proposal["category"], next_escalation_level
                )

                if not escalation_target["success"]:
                    return escalation_target

                # Update proposal metadata
                metadata = proposal.get("metadata", {})
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)

                metadata["escalation_level"] = next_escalation_level
                metadata["escalation_history"] = metadata.get("escalation_history", [])
                metadata["escalation_history"].append(
                    {
                        "level": next_escalation_level,
                        "reason": reason,
                        "escalated_at": datetime.now().isoformat(),
                        "escalated_by": escalated_by_user_id,
                        "auto_triggered": auto_triggered,
                        "escalated_to": escalation_target.get("agent_name"),
                    }
                )

                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET metadata = %s,
                        status = 'escalated'
                    WHERE id = %s
                """,
                    (json.dumps(metadata), proposal_id),
                )

                # Reassign team if needed
                if escalation_target.get("agent_id"):
                    # Remove old team lead
                    cur.execute(
                        """
                        DELETE FROM improvement_team_assignments
                        WHERE proposal_id = %s
                        AND role = 'lead'
                    """,
                        (proposal_id,),
                    )

                    # Assign new team lead
                    cur.execute(
                        """
                        INSERT INTO improvement_team_assignments
                        (proposal_id, agent_id, role, assigned_at, status)
                        VALUES (%s, %s, 'lead', NOW(), 'assigned')
                    """,
                        (proposal_id, escalation_target["agent_id"]),
                    )

                # Create notification
                try:
                    cur.execute(
                        """
                        INSERT INTO notifications
                        (user_id, type, title, message, created_at)
                        VALUES (%s, 'escalation', %s, %s, NOW())
                    """,
                        (
                            escalated_by_user_id or 1,  # Default to admin
                            f"Proposal Escalated to Level {next_escalation_level}",
                            f"Proposal #{proposal_id} has been escalated. Reason: {reason}",
                        ),
                    )
                except Exception:
                    pass  # Notifications table might not exist

                conn.commit()

                # Get new team
                cur.execute(
                    """
                    SELECT
                        ta.*,
                        a.name as agent_name,
                        a.model as agent_model
                    FROM improvement_team_assignments ta
                    JOIN agents a ON ta.agent_id = a.id
                    WHERE ta.proposal_id = %s
                """,
                    (proposal_id,),
                )

                new_team = [dict(row) for row in cur.fetchall()]

                return {
                    "success": True,
                    "proposal_id": proposal_id,
                    "escalation_level": next_escalation_level,
                    "escalated_to": escalation_target.get("agent_name"),
                    "reason": reason,
                    "new_team": new_team,
                    "auto_triggered": auto_triggered,
                }

            except Exception as e:
                conn.rollback()
                return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _find_escalation_target(self, proposal_id: int, category: str, escalation_level: int) -> Dict:
        """
        Find appropriate escalation target based on level and category.

        Level 1: Original agent
        Level 2: Senior agent (can_escalate_to from skills)
        Level 3: Department manager
        Level 4: Admin

        Args:
            proposal_id: Proposal ID
            category: Proposal category
            escalation_level: Target escalation level

        Returns:
            {
                'success': True,
                'agent_id': 123,
                'agent_name': 'Senior Engineer'
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            try:
                if escalation_level == 2:
                    # Find senior agent through can_escalate_to
                    cur.execute(
                        """
                        SELECT DISTINCT
                            se.id as agent_id,
                            se.name as agent_name,
                            se.model as agent_model
                        FROM improvement_team_assignments ta
                        JOIN agents a ON ta.agent_id = a.id
                        JOIN agent_skills askill ON a.id = askill.agent_id
                        JOIN agents se ON askill.can_escalate_to = se.id
                        WHERE ta.proposal_id = %s
                        AND se.status = 'active'
                        AND se.worker_type = 'internal'  -- Prefer internal first
                        ORDER BY se.id
                        LIMIT 1
                    """,
                        (proposal_id,),
                    )

                    senior = cur.fetchone()

                    if senior:
                        return {
                            "success": True,
                            "agent_id": senior["agent_id"],
                            "agent_name": senior["agent_name"],
                            "escalation_level": 2,
                        }

                    # Fallback: find any senior agent with matching skills
                    # Map category to skill
                    skill_mapping = {
                        "security": "security",
                        "database": "database",
                        "performance": "performance",
                        "ui": "frontend",
                        "api": "backend",
                    }

                    skill = skill_mapping.get(category, "general")

                    cur.execute(
                        """
                        SELECT
                            a.id as agent_id,
                            a.name as agent_name
                        FROM agents a
                        JOIN agent_skills askill ON a.id = askill.agent_id
                        WHERE a.status = 'active'
                        AND askill.skill_name = %s
                        AND askill.proficiency_level >= 8  -- Senior level (8-10)
                        AND a.worker_type = 'internal'
                        ORDER BY askill.proficiency_level DESC
                        LIMIT 1
                    """,
                        (skill,),
                    )

                    fallback_senior = cur.fetchone()

                    if fallback_senior:
                        return {
                            "success": True,
                            "agent_id": fallback_senior["agent_id"],
                            "agent_name": fallback_senior["agent_name"],
                            "escalation_level": 2,
                        }

                elif escalation_level == 3:
                    # Find department manager
                    # In this system, we'll use the most experienced agent in department
                    cur.execute(
                        """
                        SELECT
                            a.id as agent_id,
                            a.name as agent_name
                        FROM agents a
                        JOIN agent_skills askill ON a.id = askill.agent_id
                        WHERE a.status = 'active'
                        AND askill.proficiency_level = 10  -- Expert level
                        ORDER BY a.id
                        LIMIT 1
                    """
                    )

                    manager = cur.fetchone()

                    if manager:
                        return {
                            "success": True,
                            "agent_id": manager["agent_id"],
                            "agent_name": manager["agent_name"],
                            "escalation_level": 3,
                        }

                elif escalation_level >= 4:
                    # Escalate to admin (no specific agent, just status change)
                    return {
                        "success": True,
                        "agent_id": None,
                        "agent_name": "Admin",
                        "escalation_level": 4,
                    }

                # No escalation target found
                return {
                    "success": False,
                    "error": f"No escalation target found for level {escalation_level}",
                }

            except Exception as e:
                return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def escalate_stuck_proposal(self, proposal_id: int, reason: str) -> Dict:
        """
        Escalate a stuck proposal.

        Args:
            proposal_id: Proposal ID
            reason: Why it's stuck

        Returns:
            Escalation result
        """
        return self.escalate_proposal(proposal_id=proposal_id, reason=reason, auto_triggered=True)

    def get_escalation_history(self, proposal_id: int = None, limit: int = 20) -> Dict:
        """
        Get escalation history.

        Args:
            proposal_id: Filter by proposal (optional)
            limit: Number of results

        Returns:
            {
                'success': True,
                'escalations': [...],
                'total': 10
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            try:
                if proposal_id:
                    cur.execute(
                        """
                        SELECT * FROM improvement_proposals
                        WHERE id = %s
                    """,
                        (proposal_id,),
                    )

                    proposal = cur.fetchone()

                    if not proposal:
                        return {"success": False, "error": "Proposal not found"}

                    metadata = proposal.get("metadata", {})
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)

                    escalations = metadata.get("escalation_history", [])

                    return {
                        "success": True,
                        "proposal_id": proposal_id,
                        "escalations": escalations,
                        "total": len(escalations),
                        "current_level": metadata.get("escalation_level", 0),
                    }

                else:
                    # Get all escalated proposals
                    cur.execute(
                        """
                        SELECT
                            id,
                            title,
                            status,
                            category,
                            priority,
                            metadata
                        FROM improvement_proposals
                        WHERE status = 'escalated'
                        OR metadata::text LIKE '%escalation_level%'
                        ORDER BY created_at DESC
                        LIMIT %s
                    """,
                        (limit,),
                    )

                    proposals = cur.fetchall()

                    escalations = []
                    for p in proposals:
                        metadata = p.get("metadata", {})
                        if isinstance(metadata, str):
                            metadata = json.loads(metadata)

                        if "escalation_level" in metadata:
                            escalations.append(
                                {
                                    "proposal_id": p["id"],
                                    "title": p["title"],
                                    "status": p["status"],
                                    "escalation_level": metadata.get("escalation_level"),
                                    "escalation_history": metadata.get("escalation_history", []),
                                }
                            )

                    return {
                        "success": True,
                        "escalations": escalations,
                        "total": len(escalations),
                    }

            except Exception as e:
                return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def escalate_to_senior(proposal_id: int, reason: str) -> Dict:
    """Quick function to escalate proposal"""
    handler = EscalationHandler()
    return handler.escalate_proposal(proposal_id, reason)


def get_escalations() -> Dict:
    """Quick function to get all escalations"""
    handler = EscalationHandler()
    return handler.get_escalation_history()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Escalation Handler - Test Mode")
    print("=" * 60)

    handler = EscalationHandler()

    print("\n1. ESCALATION HISTORY:")
    print("-" * 60)
    history = handler.get_escalation_history()
    if history["success"]:
        print(f"Total escalations: {history['total']}")
        for esc in history["escalations"][:5]:  # Show first 5
            print(f"  #{esc['proposal_id']}: {esc['title']}")
            print(f"    Level: {esc['escalation_level']}")
    else:
        print(f"Error: {history.get('error')}")

    print("\n✅ Escalation Handler loaded successfully!")
