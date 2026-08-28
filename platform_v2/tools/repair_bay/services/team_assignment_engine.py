"""
Team Assignment Engine for Improvement Proposals
Automatically assigns agents to improvement proposals based on skills, availability, and cost
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from services.time_utils import now_local_str
from typing import List, Dict, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TeamAssignmentEngine:
    """
    Automatically builds and assigns teams of agents to improvement proposals.

    Key Features:
    - Internal-first routing (FREE Ollama agents before PAID API agents)
    - Skill-based matching using agent_skills table
    - Complexity-based team sizing (1-3 agents)
    - Availability checking
    - Automatic notification creation
    """

    def __init__(self, db_connection):
        """Initialize the team assignment engine with a database connection"""
        self.conn = db_connection

        # Category to required skills mapping
        self.category_skills = {
            "security": ["security_analysis", "penetration_testing", "code_review"],
            "performance": [
                "performance_optimization",
                "profiling",
                "database_optimization",
            ],
            "architecture": ["system_design", "architecture", "technical_leadership"],
            "database": ["database_design", "sql", "data_modeling"],
            "ui": ["frontend_development", "ui_design", "user_experience"],
            "api": ["api_design", "backend_development", "rest_api"],
            "integration": [
                "system_integration",
                "api_integration",
                "third_party_apis",
            ],
            "backend": ["backend_development", "python", "api_design"],
            "frontend": ["frontend_development", "javascript", "react"],
            "testing": ["testing", "test_automation", "qa"],
            "documentation": ["technical_writing", "documentation"],
            "deployment": ["devops", "deployment", "ci_cd"],
            "monitoring": ["monitoring", "logging", "observability"],
            "refactoring": ["code_review", "refactoring", "best_practices"],
        }

        # Priority to urgency mapping
        self.priority_urgency = {"high": "urgent", "medium": "normal", "low": "low"}

    def assign_team_to_proposal(
        self,
        proposal_id: int,
        force_internal: bool = False,
        user_id: Optional[int] = None,
    ) -> Dict:
        """
        Main entry point: Assign a team to an improvement proposal

        Args:
            proposal_id: ID of the improvement proposal
            force_internal: If True, only assign internal agents (fail if none available)
            user_id: ID of user triggering the assignment

        Returns:
            Dict with success status, team members, and metadata
        """
        try:
            logger.info(f"Starting team assignment for proposal #{proposal_id}")

            # 1. Get proposal details
            proposal = self._get_proposal(proposal_id)
            if not proposal:
                return {"success": False, "error": "Proposal not found"}

            # 2. Determine required skills
            required_skills = self._get_required_skills(proposal)

            # 3. Determine team size based on complexity
            team_size = self._get_team_size(proposal)

            # 4. Find available agents (internal first)
            team = self._build_team(
                required_skills=required_skills,
                team_size=team_size,
                priority=proposal["priority"],
                force_internal=force_internal,
            )

            if not team:
                return {
                    "success": False,
                    "error": "No available agents found with required skills",
                    "required_skills": required_skills,
                }

            # 5. Create team assignment records
            self._create_team_assignments(proposal_id=proposal_id, team=team, assigned_by=user_id)

            # 6. Update proposal with team info
            self._update_proposal_team_info(
                proposal_id=proposal_id,
                team_size=len(team),
                required_skills=required_skills,
            )

            # 7. Send notifications to team members
            self._notify_team(proposal=proposal, team=team)

            logger.info(f"Successfully assigned team of {len(team)} agents to proposal #{proposal_id}")

            return {
                "success": True,
                "team": team,
                "team_size": len(team),
                "required_skills": required_skills,
                "internal_count": sum(1 for agent in team if agent["worker_type"] == "internal"),
                "contract_count": sum(1 for agent in team if agent["worker_type"] == "contract"),
            }

        except Exception as e:
            logger.error(f"Error assigning team to proposal #{proposal_id}: {str(e)}")
            import traceback

            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def _get_proposal(self, proposal_id: int) -> Optional[Dict]:
        """Fetch proposal details from database"""
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, title, description, category, priority, status, complexity
            FROM improvement_proposals
            WHERE id = %s
        """,
            (proposal_id,),
        )
        proposal = cur.fetchone()
        cur.close()
        return dict(proposal) if proposal else None

    def _get_required_skills(self, proposal: Dict) -> List[str]:
        """Determine required skills based on proposal category"""
        category = proposal.get("category", "general")

        # Get skills from category mapping
        skills = self.category_skills.get(category, ["general_development"])

        # Add complexity-specific skills
        if proposal.get("complexity") == "high":
            skills.extend(["technical_leadership", "architecture"])

        return list(set(skills))  # Remove duplicates

    def _get_team_size(self, proposal: Dict) -> int:
        """Determine team size based on complexity and priority"""
        complexity = proposal.get("complexity", "medium")
        priority = proposal.get("priority", "medium")

        # Base team size on complexity
        if complexity == "high":
            base_size = 3  # Lead + Developer + Reviewer
        elif complexity == "medium":
            base_size = 2  # Lead + Developer
        else:
            base_size = 1  # Single developer

        # Increase for high priority
        if priority == "high" and base_size < 3:
            base_size += 1

        return base_size

    def _build_team(
        self,
        required_skills: List[str],
        team_size: int,
        priority: str,
        force_internal: bool = False,
    ) -> List[Dict]:
        """
        Build a team of agents based on skills and availability.
        Internal agents (FREE) are prioritized over contract agents (PAID).
        """
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        team = []

        # Define roles based on team size
        roles = ["lead", "developer", "reviewer", "tester"][:team_size]

        for role in roles:
            # Try to find internal agent first
            agent = self._find_best_agent(
                required_skills=required_skills,
                role=role,
                worker_type="internal",
                exclude_ids=[a["id"] for a in team],
            )

            # If no internal agent and not forced, try contract agents
            if not agent and not force_internal:
                agent = self._find_best_agent(
                    required_skills=required_skills,
                    role=role,
                    worker_type="contract",
                    exclude_ids=[a["id"] for a in team],
                )

            # If still no agent, try any available agent (fallback)
            if not agent and not force_internal:
                agent = self._find_best_agent(
                    required_skills=required_skills,
                    role=role,
                    worker_type=None,  # Any type
                    exclude_ids=[a["id"] for a in team],
                )

            if agent:
                agent["role"] = role
                team.append(agent)
            else:
                logger.warning(f"Could not find agent for role: {role}")

        cur.close()
        return team

    def _find_best_agent(
        self,
        required_skills: List[str],
        role: str,
        worker_type: Optional[str] = None,
        exclude_ids: List[int] = [],
    ) -> Optional[Dict]:
        """
        Find the best available agent matching requirements.
        Scoring: Skill proficiency + Availability
        """
        cur = self.conn.cursor(cursor_factory=RealDictCursor)

        # Build query to find agents with matching skills
        worker_type_filter = f"AND a.worker_type = '{worker_type}'" if worker_type else ""
        exclude_filter = f"AND a.id NOT IN ({','.join(map(str, exclude_ids))})" if exclude_ids else ""

        query = f"""
            SELECT
                a.id,
                a.name,
                a.worker_type,
                a.department,
                a.tier,
                COALESCE(AVG(ags.proficiency_level), 0) as avg_skill_level,
                COUNT(DISTINCT ags.skill_name) as matching_skills,
                COALESCE(a.last_used, '2000-01-01'::timestamp) as last_used
            FROM agents a
            LEFT JOIN agent_skills ags ON a.id = ags.agent_id
            WHERE a.status = 'active'
            AND (ags.skill_name = ANY(%s) OR %s = '{{}}')
            {worker_type_filter}
            {exclude_filter}
            GROUP BY a.id
            ORDER BY
                matching_skills DESC,
                avg_skill_level DESC,
                a.worker_type = 'internal' DESC,  -- Prefer internal
                last_used ASC  -- Least recently used
            LIMIT 1
        """

        cur.execute(query, (required_skills, required_skills))
        agent = cur.fetchone()
        cur.close()

        return dict(agent) if agent else None

    def _create_team_assignments(self, proposal_id: int, team: List[Dict], assigned_by: Optional[int] = None):
        """Create team assignment records in database"""
        from services import agent_service

        cur = self.conn.cursor()

        for agent in team:
            cur.execute(
                """
                INSERT INTO improvement_team_assignments
                (proposal_id, agent_id, role, status, assigned_by, assigned_at)
                VALUES (%s, %s, %s, 'assigned', %s, NOW())
                ON CONFLICT (proposal_id, agent_id) DO NOTHING
            """,
                (proposal_id, agent["id"], agent["role"], assigned_by),
            )

        self.conn.commit()
        cur.close()

        # Single-writer path: agents.last_used bookkeeping goes through
        # agent_service.update_agent so the agents table only has one
        # canonical mutation surface (Project #241 Track C.1).
        now = datetime.now()
        for agent in team:
            try:
                agent_service.update_agent(agent["id"], last_used=now)
            except Exception as exc:
                logger.warning(f"Failed to bump last_used for agent {agent['id']}: {exc}")

    def _update_proposal_team_info(self, proposal_id: int, team_size: int, required_skills: List[str]):
        """Update proposal with team assignment metadata"""
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                team_size = %s,
                team_assigned_at = NOW(),
                required_skills = %s,
                status = CASE
                    WHEN status = 'proposed' THEN 'pending_approval'
                    ELSE status
                END
            WHERE id = %s
        """,
            (team_size, required_skills, proposal_id),
        )
        self.conn.commit()
        cur.close()

    def _notify_team(self, proposal: Dict, team: List[Dict]):
        """Send notifications to all assigned team members"""
        cur = self.conn.cursor()

        for agent in team:
            # For now, send to admin user (id=2) as a proxy
            # TODO: Link agents to actual user accounts for direct notifications
            cur.execute(
                """
                INSERT INTO notifications
                (user_id, type, title, message, priority, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    2,  # Admin user
                    "task_assigned",
                    f'🎯 Team Assignment: {agent["name"]} → Proposal #{proposal["id"]}',
                    f'Agent {agent["name"]} has been assigned as {agent["role"]} for proposal "{proposal["title"]}"',
                    self.priority_urgency.get(proposal["priority"], "normal"),
                    {
                        "proposal_id": proposal["id"],
                        "agent_id": agent["id"],
                        "role": agent["role"],
                        "worker_type": agent["worker_type"],
                    },
                ),
            )

        self.conn.commit()
        cur.close()

    def get_team_for_proposal(self, proposal_id: int) -> List[Dict]:
        """Get currently assigned team for a proposal"""
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                ta.id as assignment_id,
                ta.role,
                ta.status,
                ta.assigned_at,
                ta.completed_at,
                a.id as agent_id,
                a.name as agent_name,
                a.worker_type,
                a.department,
                a.tier
            FROM improvement_team_assignments ta
            JOIN agents a ON ta.agent_id = a.id
            WHERE ta.proposal_id = %s
            ORDER BY ta.assigned_at
        """,
            (proposal_id,),
        )
        team = cur.fetchall()
        cur.close()
        return [dict(row) for row in team]

    def reassign_agent(self, assignment_id: int, new_agent_id: int, reason: str = "Manual reassignment") -> bool:
        """Reassign a specific team member to a different agent"""
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)

            # Get current assignment
            cur.execute(
                """
                SELECT proposal_id, agent_id, role
                FROM improvement_team_assignments
                WHERE id = %s
            """,
                (assignment_id,),
            )
            assignment = cur.fetchone()

            if not assignment:
                return False

            # Update assignment
            cur.execute(
                """
                UPDATE improvement_team_assignments
                SET
                    agent_id = %s,
                    notes = COALESCE(notes || E'\n\n', '') || %s,
                    assigned_at = NOW(),
                    status = 'assigned'
                WHERE id = %s
            """,
                (
                    new_agent_id,
                    f"[REASSIGNED] {reason} at {now_local_str()}",
                    assignment_id,
                ),
            )

            self.conn.commit()
            cur.close()

            # Single-writer path for agents.last_used (Project #241 Track C.1).
            # Note: Workload tracking (current_load) not yet implemented.
            try:
                from services import agent_service

                agent_service.update_agent(new_agent_id, last_used=datetime.now())
            except Exception as exc:
                logger.warning(f"Failed to bump last_used for new agent {new_agent_id}: {exc}")

            return True

        except Exception as e:
            logger.error(f"Error reassigning agent: {str(e)}")
            return False


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def get_db_connection():
    """Get database connection (import from main app config)"""
    import os
    from database import _get_db_password

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def assign_team_to_proposal(proposal_id: int, force_internal: bool = False, user_id: Optional[int] = None) -> Dict:
    """
    Quick function to assign a team to a proposal.

    Args:
        proposal_id: ID of the improvement proposal
        force_internal: If True, only assign internal agents
        user_id: Optional ID of user triggering the assignment

    Usage:
        result = assign_team_to_proposal(proposal_id=123)
        if result['success']:
            print(f"Assigned team of {result['team_size']} agents")
        else:
            print(f"Error: {result['error']}")
    """
    conn = get_db_connection()
    engine = TeamAssignmentEngine(conn)
    result = engine.assign_team_to_proposal(proposal_id, force_internal, user_id)
    conn.close()
    return result


def get_team_for_proposal(proposal_id: int) -> List[Dict]:
    """Get the currently assigned team for a proposal"""
    conn = get_db_connection()
    engine = TeamAssignmentEngine(conn)
    team = engine.get_team_for_proposal(proposal_id)
    conn.close()
    return team


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test the team assignment engine
    print("Team Assignment Engine - Test Mode")
    print("=" * 60)

    # Example: Assign team to proposal #1
    result = assign_team_to_proposal(proposal_id=1, force_internal=True)

    if result["success"]:
        print(f"✅ Success! Assigned team of {result['team_size']} agents:")
        for agent in result["team"]:
            print(f"   - {agent['name']} ({agent['role']}) - {agent['worker_type']}")
        print(f"\nInternal agents: {result['internal_count']}")
        print(f"Contract agents: {result['contract_count']}")
    else:
        print(f"❌ Error: {result['error']}")
