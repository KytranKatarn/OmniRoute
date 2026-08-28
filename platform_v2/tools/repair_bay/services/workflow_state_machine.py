"""
Workflow State Machine
Manages improvement proposal workflow with proper state transitions and gates

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-05
"""

import os
from database import _get_db_password
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Optional, List
from enum import Enum


class ProposalState(Enum):
    """Valid proposal states"""

    PROPOSED = "proposed"
    APPROVED = "approved"
    GENERATING_CODE = "generating_code"
    CODE_GENERATED = "code_generated"
    CREATING_SANDBOX = "creating_sandbox"
    SANDBOX_CREATED = "sandbox_created"
    APPLYING_CHANGES = "applying_changes"
    READY_FOR_TESTING = "ready_for_testing"
    TESTING = "testing"
    TESTED = "tested"
    READY_FOR_REVIEW = "ready_for_review"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class WorkflowStateMachine:
    """Manages proposal workflow state transitions"""

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

    def transition_state(
        self,
        proposal_id: int,
        to_state: str,
        reason: Optional[str] = None,
        automated: bool = True,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Transition a proposal to a new state

        Args:
            proposal_id: Proposal ID
            to_state: Target state
            reason: Reason for transition
            automated: Was this automated or manual?
            metadata: Additional metadata

        Returns:
            {
                'success': bool,
                'from_state': str,
                'to_state': str,
                'allowed': bool,
                'message': str
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get current state
            cur.execute(
                """
                SELECT id, status, title, category
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()

            if not proposal:
                return {"success": False, "error": f"Proposal {proposal_id} not found"}

            from_state = proposal["status"]

            # Validate transition
            validation = self._validate_transition(from_state, to_state)

            if not validation["allowed"]:
                cur.close()
                conn.close()
                return {
                    "success": False,
                    "from_state": from_state,
                    "to_state": to_state,
                    "allowed": False,
                    "message": validation["reason"],
                }

            # Update proposal status
            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = %s
                WHERE id = %s
            """,
                (to_state, proposal_id),
            )

            # Record state transition
            cur.execute(
                """
                INSERT INTO improvement_workflow_states
                (proposal_id, from_status, to_status, reason, automated, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    proposal_id,
                    from_state,
                    to_state,
                    reason or f"Transition from {from_state} to {to_state}",
                    automated,
                    psycopg2.extras.Json(metadata) if metadata else None,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "from_state": from_state,
                "to_state": to_state,
                "allowed": True,
                "message": f"Transitioned from {from_state} to {to_state}",
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()

            return {"success": False, "error": str(e)}

    def _validate_transition(self, from_state: str, to_state: str) -> Dict:
        """
        Validate if a state transition is allowed

        Returns:
            {
                'allowed': bool,
                'reason': str
            }
        """
        # Define valid transitions
        valid_transitions = {
            "proposed": ["approved", "rejected"],
            "approved": ["generating_code", "failed"],
            "generating_code": ["code_generated", "failed"],
            "code_generated": ["creating_sandbox", "failed"],
            "creating_sandbox": ["sandbox_created", "failed"],
            "sandbox_created": ["applying_changes", "failed"],
            "applying_changes": ["ready_for_testing", "failed"],
            "ready_for_testing": ["testing"],
            "testing": ["tested", "failed"],
            "tested": ["ready_for_review"],
            "ready_for_review": ["deploying", "rejected"],
            "deploying": ["deployed", "failed"],
            "deployed": ["completed"],
            "failed": ["proposed"],  # Can retry failed proposals
            "rejected": [],  # Terminal state
        }

        allowed_next_states = valid_transitions.get(from_state, [])

        if to_state in allowed_next_states:
            return {
                "allowed": True,
                "reason": f"Valid transition from {from_state} to {to_state}",
            }
        else:
            return {
                "allowed": False,
                "reason": f'Invalid transition from {from_state} to {to_state}. Allowed: {", ".join(allowed_next_states)}',
            }

    def get_next_allowed_states(self, proposal_id: int) -> List[str]:
        """Get list of allowed next states for a proposal"""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT status FROM improvement_proposals WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()
        cur.close()
        conn.close()

        if not proposal:
            return []

        current_state = proposal["status"]

        valid_transitions = {
            "proposed": ["approved", "rejected"],
            "approved": ["generating_code"],
            "generating_code": ["code_generated", "failed"],
            "code_generated": ["creating_sandbox"],
            "creating_sandbox": ["sandbox_created", "failed"],
            "sandbox_created": ["applying_changes"],
            "applying_changes": ["ready_for_testing", "failed"],
            "ready_for_testing": ["testing"],
            "testing": ["tested", "failed"],
            "tested": ["ready_for_review"],
            "ready_for_review": ["deploying", "rejected"],
            "deploying": ["deployed", "failed"],
            "deployed": ["completed"],
        }

        return valid_transitions.get(current_state, [])

    def get_workflow_progress(self, proposal_id: int) -> Dict:
        """
        Get workflow progress for a proposal

        Returns:
            {
                'current_state': str,
                'progress_percent': int,
                'completed_states': list,
                'remaining_states': list,
                'history': list
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current state
        cur.execute(
            """
            SELECT status FROM improvement_proposals WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()

        if not proposal:
            cur.close()
            conn.close()
            return {"error": "Proposal not found"}

        current_state = proposal["status"]

        # Get workflow history
        cur.execute(
            """
            SELECT from_status, to_status, changed_at, reason, automated
            FROM improvement_workflow_states
            WHERE proposal_id = %s
            ORDER BY changed_at ASC
        """,
            (proposal_id,),
        )

        history = [dict(row) for row in cur.fetchall()]

        cur.close()
        conn.close()

        # Define standard workflow path
        standard_path = [
            "proposed",
            "approved",
            "generating_code",
            "code_generated",
            "creating_sandbox",
            "sandbox_created",
            "applying_changes",
            "ready_for_testing",
            "testing",
            "tested",
            "ready_for_review",
            "deploying",
            "deployed",
            "completed",
        ]

        # Calculate progress
        try:
            current_index = standard_path.index(current_state)
            progress_percent = int((current_index / len(standard_path)) * 100)
            completed_states = standard_path[: current_index + 1]
            remaining_states = standard_path[current_index + 1 :]
        except ValueError:
            # State not in standard path (e.g., failed, rejected)
            progress_percent = 0
            completed_states = [current_state]
            remaining_states = []

        return {
            "current_state": current_state,
            "progress_percent": progress_percent,
            "completed_states": completed_states,
            "remaining_states": remaining_states,
            "history": history,
        }


# Convenience functions
def transition_proposal_state(
    proposal_id: int,
    to_state: str,
    reason: Optional[str] = None,
    automated: bool = True,
) -> Dict:
    """Transition a proposal to a new state"""
    machine = WorkflowStateMachine()
    return machine.transition_state(proposal_id, to_state, reason, automated)


def get_proposal_progress(proposal_id: int) -> Dict:
    """Get workflow progress for a proposal"""
    machine = WorkflowStateMachine()
    return machine.get_workflow_progress(proposal_id)


if __name__ == "__main__":
    # Test workflow state machine
    print("=" * 80)
    print("Workflow State Machine - Test")
    print("=" * 80)

    # Test transition
    result = transition_proposal_state(proposal_id=39, to_state="proposed", reason="Reset for testing")

    print(f"\n✅ Transition success: {result.get('success')}")
    print(f"📊 From: {result.get('from_state')} → To: {result.get('to_state')}")

    # Test progress
    progress = get_proposal_progress(39)
    print(f"\n📈 Progress: {progress.get('progress_percent')}%")
    print(f"📍 Current: {progress.get('current_state')}")
    print(f"✅ Completed: {len(progress.get('completed_states', []))} states")
    print(f"⏳ Remaining: {len(progress.get('remaining_states', []))} states")
