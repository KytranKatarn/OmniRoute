"""
Team Consensus Orchestrator
Automates the multi-agent collaborative evaluation workflow

Author: A.R.C.H.I.E.
Date: 2026-01-01
Purpose: Orchestrate automatic team discussions, evaluations, and consensus building for proposals
"""

import os
import sys
import json
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_v2.database import get_db
from ai_bridge.team_discussion_engine import TeamDiscussionEngine
from ai_bridge.collaborative_report_generator import (
    CollaborativeReportGenerator,
    DecimalEncoder,
)
import re
import logging

logger = logging.getLogger(__name__)


class TeamConsensusOrchestrator:
    """Orchestrates the complete team consensus workflow"""

    def __init__(self):
        self.discussion_engine = TeamDiscussionEngine()
        self.report_generator = CollaborativeReportGenerator()

    def select_evaluation_team(
        self,
        proposal_id: int,
        category: str = None,
        priority: str = "medium",
        min_agents: int = 2,
        max_agents: int = 4,
    ) -> List[int]:
        """
        Automatically select agents for proposal evaluation

        Args:
            proposal_id: ID of the proposal
            category: Proposal category (backend, frontend, database, etc.)
            priority: Proposal priority (low, medium, high, critical)
            min_agents: Minimum number of agents to assign
            max_agents: Maximum number of agents to assign

        Returns:
            List of selected agent IDs
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Priority-based team size
            team_size_map = {
                "low": min_agents,
                "medium": min_agents + 1,
                "high": max_agents - 1,
                "critical": max_agents,
            }
            target_team_size = team_size_map.get(priority, min_agents + 1)

            # Category-to-department mapping
            category_dept_map = {
                "backend": "Engineering",
                "frontend": "Engineering",
                "database": "Operations",
                "infrastructure": "Operations",
                "security": "Security",
                "api": "Engineering",
                "ui_ux": "Design",
                "performance": "QA",
                "testing": "QA",
            }

            preferred_dept = category_dept_map.get(category, "Engineering")

            # A.R.C.H.I.E. is the facilitator — exclude from candidate pool.
            # Single-source path: look up the id via agent_service rather than
            # a raw SELECT subquery so the agents-table ownership stays with
            # Department HQ (Project #242 Task 8 / Project #241 Track C).
            from services import agent_service

            archie = agent_service.get_agent_by_name("A.R.C.H.I.E.")
            archie_id = archie["id"] if archie else 0

            # Select internal agents first (FREE), prioritize by department match
            cur.execute(
                """
                SELECT
                    a.id,
                    a.name,
                    a.department,
                    a.tier,
                    CASE WHEN a.department = %s THEN 1 ELSE 2 END as dept_priority
                FROM agents a
                WHERE a.status = 'active'
                AND a.worker_type = 'internal'
                AND a.id != %s  -- Exclude A.R.C.H.I.E. (facilitator)
                ORDER BY dept_priority ASC, a.tier ASC, RANDOM()
                LIMIT %s
            """,
                (preferred_dept, archie_id, target_team_size),
            )

            selected_agents = cur.fetchall()
            agent_ids = [agent[0] for agent in selected_agents]

            # If not enough internal agents, add contractors
            if len(agent_ids) < min_agents:
                needed = min_agents - len(agent_ids)
                cur.execute(
                    """
                    SELECT a.id
                    FROM agents a
                    WHERE a.status = 'active'
                    AND a.worker_type = 'contract'
                    AND a.id NOT IN %s
                    ORDER BY a.tier ASC, RANDOM()
                    LIMIT %s
                """,
                    (tuple(agent_ids) if agent_ids else (0,), needed),
                )

                contractors = cur.fetchall()
                agent_ids.extend([c[0] for c in contractors])

            cur.close()
            conn.close()

            print(f"✅ Selected {len(agent_ids)} agents for proposal #{proposal_id} evaluation")
            return agent_ids

        except Exception as e:
            print(f"Error selecting evaluation team: {e}")
            import traceback

            traceback.print_exc()
            return []

    def simulate_agent_evaluation(self, agent_id: int, proposal_id: int, proposal_data: Dict) -> Dict:
        """
        Simulate an agent's evaluation of a proposal
        (This will be replaced with real AI agent calls in the future)

        Args:
            agent_id: ID of the evaluating agent
            proposal_id: ID of the proposal
            proposal_data: Proposal details

        Returns:
            Dictionary with evaluation data
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Get agent info
            cur.execute(
                """
                SELECT name, department, tier, worker_type
                FROM agents WHERE id = %s
            """,
                (agent_id,),
            )
            agent_info = cur.fetchone()
            cur.close()
            conn.close()

            if not agent_info:
                return {}

            agent_name, department, tier, worker_type = agent_info

            # Simulated evaluation based on department and tier
            # Higher tier = higher confidence, more detailed analysis
            base_confidence = 0.7 + (tier * 0.05)  # Tier 1: 0.75, Tier 2: 0.80, etc.

            # Department-specific evaluation tendencies
            dept_recommendations = {
                "Engineering": "approve",  # Tend to approve technical changes
                "QA": "needs_testing",  # Always want testing
                "Security": "needs_changes",  # Cautious about security
                "Operations": "approve",  # Approve infrastructure changes
                "Design": "approve",  # Approve UX improvements
            }

            recommendation = dept_recommendations.get(department, "needs_review")

            # Risk assessment based on priority and category
            priority = proposal_data.get("priority", "medium")
            risk_map = {
                "low": "low",
                "medium": "medium",
                "high": "high",
                "critical": "critical",
            }
            risk_assessment = risk_map.get(priority, "medium")

            # Effort estimation
            effort_map = {
                "low": "1-2h",
                "medium": "2-4h",
                "high": "1-2d",
                "critical": "3-5d",
            }
            estimated_effort = effort_map.get(priority, "2-4h")

            # Generate evaluation details
            evaluation = {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "recommendation": recommendation,
                "confidence_level": min(base_confidence, 1.0),
                "risk_assessment": risk_assessment,
                "estimated_effort": estimated_effort,
                "technical_notes": f"[{agent_name}] Analyzed proposal from {department} perspective. "
                f"Recommendation: {recommendation}. Risk level: {risk_assessment}.",
                "manager_summary": f"{agent_name} from {department} recommends: {recommendation}. "
                f"This change has {risk_assessment} risk and will take approximately {estimated_effort}.",
                "concerns": self._generate_concerns(department, proposal_data),
                "benefits": self._generate_benefits(department, proposal_data),
                "role": "reviewer",
            }

            return evaluation

        except Exception as e:
            print(f"Error simulating agent evaluation: {e}")
            import traceback

            traceback.print_exc()
            return {}

    def get_real_agent_evaluation(
        self, agent_id: int, proposal_id: int, proposal_data: Dict, user_id: int = None
    ) -> Dict:
        """
        Get REAL evaluation from agent via Bridge dispatcher

        Args:
            agent_id: ID of the evaluating agent
            proposal_id: ID of the proposal
            proposal_data: Proposal details
            user_id: User ID for tracking (optional)

        Returns:
            Dictionary with evaluation data from real AI response
        """
        try:
            # Import dispatcher here to avoid circular imports
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            _dispatcher = get_dispatcher()

            conn = get_db()
            cur = conn.cursor()

            # Get comprehensive agent info
            cur.execute(
                """
                SELECT
                    name, department, title, tier, worker_type,
                    model, system_prompt, personality_prompt,
                    communication_style, capabilities, learned_skills
                FROM agents WHERE id = %s
            """,
                (agent_id,),
            )
            agent_row = cur.fetchone()
            cur.close()
            conn.close()

            if not agent_row:
                logger.warning(f"Agent {agent_id} not found, falling back to simulation")
                return self.simulate_agent_evaluation(agent_id, proposal_id, proposal_data)

            (
                agent_name,
                department,
                title,
                tier,
                worker_type,
                model,
                system_prompt,
                personality_prompt,
                communication_style,
                capabilities,
                learned_skills,
            ) = agent_row

            # Build agent-specific evaluation prompt
            skills_str = ", ".join(capabilities.get("skills", [])) if capabilities else "general analysis"
            comm_style = communication_style or "professional and analytical"

            # Build the system prompt for evaluation
            eval_system_prompt = f"""You are {agent_name}, a {title} in the {department} department.

Your expertise includes: {skills_str}
Your communication style: {comm_style}

You are evaluating an improvement proposal. Provide a thorough, professional evaluation based on your expertise.

IMPORTANT: Respond ONLY with a valid JSON object in this exact format:
{{
    "recommendation": "approve" | "reject" | "needs_changes" | "needs_testing",
    "confidence": 0.0 to 1.0,
    "risk_level": "low" | "medium" | "high" | "critical",
    "estimated_effort": "1-2h" | "2-4h" | "4-8h" | "1-2d" | "3-5d",
    "concerns": ["concern 1", "concern 2"],
    "benefits": ["benefit 1", "benefit 2"],
    "technical_notes": "Your detailed technical analysis",
    "manager_summary": "Brief executive summary for non-technical stakeholders"
}}

Do not include any text before or after the JSON object."""

            # Build the evaluation prompt
            eval_prompt = f"""## Improvement Proposal #{proposal_id}

**Title:** {proposal_data.get('title', 'Untitled')}
**Category:** {proposal_data.get('category', 'general')}
**Priority:** {proposal_data.get('priority', 'medium')}

**Description:**
{proposal_data.get('description', 'No description provided')}

**Code Changes (if specified):**
{proposal_data.get('code_changes', 'Not specified')}

Please evaluate this proposal from your perspective as {title} in {department}. Consider:
- Technical feasibility and implementation complexity
- Potential risks and mitigation strategies
- Impact on existing systems
- Alignment with best practices in your domain

Provide your evaluation in JSON format."""

            # Call Bridge dispatcher with agent's assigned model
            logger.info(f"Getting real evaluation from {agent_name} (ID: {agent_id}) using model: {model}")

            result = _dispatcher.request_work(
                capability="code_review",
                prompt=eval_prompt,
                module_id="improvement_labs",
                system_prompt=eval_system_prompt,
                user_id=user_id,
                prefer_agent=agent_name,
            )

            if not result.success:
                logger.warning(f"Dispatcher failed for agent {agent_id}, falling back to simulation")
                return self.simulate_agent_evaluation(agent_id, proposal_id, proposal_data)

            # Parse the response
            response_text = result.response or ""
            evaluation = self._parse_evaluation_response(response_text, agent_id, agent_name, department, tier)

            logger.info(
                f"Real evaluation from {agent_name}: {evaluation.get('recommendation')} (confidence: {evaluation.get('confidence_level', 0):.2f})"
            )

            return evaluation

        except Exception as e:
            logger.error(f"Error getting real agent evaluation: {e}")
            import traceback

            traceback.print_exc()
            # Fall back to simulation on error
            return self.simulate_agent_evaluation(agent_id, proposal_id, proposal_data)

    def _parse_evaluation_response(
        self,
        response_text: str,
        agent_id: int,
        agent_name: str,
        department: str,
        tier: int,
    ) -> Dict:
        """
        Parse the JSON evaluation response from an agent

        Args:
            response_text: Raw response from Bridge dispatcher
            agent_id: Agent ID
            agent_name: Agent name
            department: Agent department
            tier: Agent tier

        Returns:
            Structured evaluation dictionary
        """
        try:
            # Try to extract JSON from response
            # Handle cases where there might be markdown code blocks
            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if not json_match:
                raise ValueError("No JSON object found in response")

            json_str = json_match.group()
            parsed = json.loads(json_str)

            # Map parsed response to our evaluation structure
            confidence = float(parsed.get("confidence", 0.7))

            evaluation = {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "recommendation": parsed.get("recommendation", "needs_review"),
                "confidence_level": min(max(confidence, 0.0), 1.0),  # Clamp 0-1
                "risk_assessment": parsed.get("risk_level", "medium"),
                "estimated_effort": parsed.get("estimated_effort", "2-4h"),
                "technical_notes": parsed.get("technical_notes", f"[{agent_name}] Evaluation complete."),
                "manager_summary": parsed.get(
                    "manager_summary",
                    f"{agent_name} from {department} has reviewed this proposal.",
                ),
                "concerns": parsed.get("concerns", []),
                "benefits": parsed.get("benefits", []),
                "role": "reviewer",
                "real_ai_evaluation": True,  # Flag to indicate this came from real AI
            }

            return evaluation

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse evaluation response: {e}")
            # Return a partial evaluation with the raw response
            base_confidence = 0.7 + (tier * 0.05)
            return {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "recommendation": "needs_review",
                "confidence_level": base_confidence,
                "risk_assessment": "medium",
                "estimated_effort": "2-4h",
                "technical_notes": (response_text[:500] if response_text else f"[{agent_name}] Evaluation pending."),
                "manager_summary": f"{agent_name} from {department} has provided feedback.",
                "concerns": ["Unable to parse structured evaluation"],
                "benefits": ["Agent provided response"],
                "role": "reviewer",
                "real_ai_evaluation": True,
                "parse_error": True,
            }

    def _generate_concerns(self, department: str, proposal_data: Dict) -> List[str]:
        """Generate department-specific concerns"""
        concerns_map = {
            "Engineering": [
                "Potential code complexity increase",
                "May require additional testing",
                "Consider backward compatibility",
            ],
            "QA": [
                "Needs comprehensive test coverage",
                "Regression testing required",
                "Performance impact needs measurement",
            ],
            "Security": [
                "Security implications need review",
                "Authentication/authorization changes required",
                "Data privacy considerations",
            ],
            "Operations": [
                "Infrastructure scaling considerations",
                "Deployment rollback plan needed",
                "Monitoring and alerting updates required",
            ],
            "Design": [
                "User experience impact",
                "Accessibility requirements",
                "Cross-browser compatibility",
            ],
        }

        return concerns_map.get(department, ["Requires careful review"])

    def _generate_benefits(self, department: str, proposal_data: Dict) -> List[str]:
        """Generate department-specific benefits"""
        benefits_map = {
            "Engineering": [
                "Improved code maintainability",
                "Better performance",
                "Reduced technical debt",
            ],
            "QA": [
                "Improved testability",
                "Better error handling",
                "Enhanced reliability",
            ],
            "Security": [
                "Stronger security posture",
                "Reduced attack surface",
                "Better compliance",
            ],
            "Operations": [
                "Improved system stability",
                "Better resource utilization",
                "Enhanced monitoring capabilities",
            ],
            "Design": [
                "Better user experience",
                "Improved accessibility",
                "Modern interface",
            ],
        }

        return benefits_map.get(department, ["Positive improvement"])

    def orchestrate_team_evaluation(
        self,
        proposal_id: int,
        auto_generate_report: bool = True,
        auto_notify_admin: bool = True,
        use_real_ai: bool = True,
        user_id: int = None,
    ) -> Optional[int]:
        """
        Orchestrate the complete team evaluation workflow

        Args:
            proposal_id: ID of the proposal to evaluate
            auto_generate_report: Automatically generate collaborative report
            auto_notify_admin: Automatically notify admin of consensus
            use_real_ai: Use real AI evaluations via Bridge dispatcher (default: True)
            user_id: User ID for tracking (optional)

        Returns:
            Discussion ID if successful, None otherwise

        Workflow:
            1. Get proposal details
            2. Select evaluation team
            3. Start discussion
            4. Collect agent evaluations (REAL AI via Bridge dispatcher or simulated)
            5. Calculate consensus
            6. Create team consensus record
            7. Generate reports (optional)
            8. Notify admin (optional)
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Step 1: Get proposal details
            cur.execute(
                """
                SELECT
                    id, title, description, category, priority, status
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                print(f"Proposal #{proposal_id} not found")
                return None

            prop_id, title, description, category, priority, status = proposal
            proposal_data = {
                "id": prop_id,
                "title": title,
                "description": description,
                "category": category,
                "priority": priority,
                "status": status,
            }

            # Step 2: Select evaluation team
            agent_ids = self.select_evaluation_team(proposal_id=proposal_id, category=category, priority=priority)

            if not agent_ids:
                print("Failed to select evaluation team")
                return None

            # Step 3: Start discussion
            discussion_id = self.discussion_engine.start_discussion(
                proposal_id=proposal_id,
                topic=f"Team Evaluation: {title}",
                description=f"Automated team evaluation of proposal #{proposal_id}",
            )

            if not discussion_id:
                print("Failed to start discussion")
                return None

            # Assign agents to discussion
            self.discussion_engine.assign_agents_to_discussion(discussion_id, agent_ids)

            # Step 4: Collect agent evaluations (REAL AI or simulated)
            real_ai_count = 0
            for agent_id in agent_ids:
                if use_real_ai:
                    evaluation = self.get_real_agent_evaluation(
                        agent_id=agent_id,
                        proposal_id=proposal_id,
                        proposal_data=proposal_data,
                        user_id=user_id,
                    )
                    if evaluation.get("real_ai_evaluation"):
                        real_ai_count += 1
                else:
                    evaluation = self.simulate_agent_evaluation(
                        agent_id=agent_id,
                        proposal_id=proposal_id,
                        proposal_data=proposal_data,
                    )

                if evaluation:
                    # Add discussion contribution
                    self.discussion_engine.agent_contribute(
                        discussion_id=discussion_id,
                        agent_id=agent_id,
                        message=evaluation["technical_notes"],
                        message_type="analysis",
                        confidence_score=evaluation["confidence_level"],
                    )

                    # Create formal evaluation (remove agent_name as it's not a parameter)
                    eval_params = {k: v for k, v in evaluation.items() if k != "agent_name"}
                    self.discussion_engine.create_agent_evaluation(
                        proposal_id=proposal_id,
                        discussion_id=discussion_id,
                        **eval_params,
                    )

            # Step 5: Calculate consensus
            consensus_score, stats = self.discussion_engine.calculate_consensus(discussion_id)

            print(f"✅ Consensus calculated: {consensus_score:.2f} ({stats['final_recommendation']})")

            # Step 6: Create team consensus record
            consensus_id = self.discussion_engine.create_team_consensus(
                proposal_id=proposal_id,
                discussion_id=discussion_id,
                implementation_plan="To be determined by assigned implementation team",
                priority_recommendation=priority,
            )

            # Close discussion
            self.discussion_engine.close_discussion(discussion_id, consensus_reached=True)

            # Step 7: Generate reports (if requested)
            if auto_generate_report:
                full_report = self.report_generator.generate_full_report(discussion_id)
                if full_report:
                    self.report_generator.save_report_to_database(discussion_id, full_report)
                    print(f"✅ Report generated and saved for discussion #{discussion_id}")

            # Step 8: Notify admin (if requested)
            if auto_notify_admin:
                notification_data = self.report_generator.generate_notification_report(discussion_id)
                if notification_data:
                    self._create_admin_notification(proposal_id, discussion_id, notification_data)

            cur.close()
            conn.close()

            print(f"✅ Team evaluation complete for proposal #{proposal_id}")
            print(f"   Discussion ID: {discussion_id}")
            print(f"   Consensus ID: {consensus_id}")
            print(f"   Recommendation: {stats['final_recommendation']}")
            print(f"   Consensus Score: {consensus_score:.2f}")
            if use_real_ai:
                print(f"   Real AI Evaluations: {real_ai_count}/{len(agent_ids)}")

            return discussion_id

        except Exception as e:
            print(f"Error orchestrating team evaluation: {e}")
            import traceback

            traceback.print_exc()
            return None

    def _create_admin_notification(self, proposal_id: int, discussion_id: int, notification_data: Dict) -> bool:
        """Create notification for admin about consensus"""
        try:
            conn = get_db()
            cur = conn.cursor()

            # Determine notification type based on recommendation
            recommendation = notification_data.get("recommendation", "needs_review")
            notification_type = {
                "approved": "success",
                "rejected": "warning",
                "needs_revision": "info",
            }.get(recommendation, "info")

            title = f"Team Consensus: {notification_data.get('proposal_title', 'Proposal')}"
            message = notification_data.get("quick_summary", "Team evaluation complete")

            # Create notification
            metadata = {
                "source": "team_consensus",
                "proposal_id": proposal_id,
                "discussion_id": discussion_id,
                "recommendation": recommendation,
                "consensus_score": notification_data.get("consensus_score", 0),
                "vote_summary": notification_data.get("vote_summary", ""),
            }

            # Determine priority based on recommendation
            priority_map = {
                "approved": "high",
                "rejected": "normal",
                "needs_revision": "normal",
                "needs_testing": "high",
            }
            priority = priority_map.get(recommendation, "normal")

            # Get admin user ID for system notifications
            cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            admin_user = cur.fetchone()
            user_id = admin_user[0] if admin_user else 1  # Default to user ID 1 if no admin found

            cur.execute(
                """
                INSERT INTO notifications (
                    user_id, type, title, message, metadata, priority, action_url, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """,
                (
                    user_id,
                    notification_type,
                    title,
                    message,
                    json.dumps(metadata, cls=DecimalEncoder),
                    priority,
                    f"/tools/admin#improvements-proposal-{proposal_id}",
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Admin notification created for proposal #{proposal_id}")
            return True

        except Exception as e:
            print(f"Error creating notification: {e}")
            import traceback

            traceback.print_exc()
            return False


# Convenience functions
def auto_evaluate_proposal(
    proposal_id: int,
    generate_report: bool = True,
    notify_admin: bool = True,
    use_real_ai: bool = True,
    user_id: int = None,
) -> Optional[int]:
    """
    Automatically evaluate a proposal with team consensus

    Args:
        proposal_id: ID of the proposal to evaluate
        generate_report: Generate collaborative report
        notify_admin: Notify admin of results
        use_real_ai: Use real AI evaluations via Bridge dispatcher (default: True)
        user_id: User ID for tracking

    Returns:
        Discussion ID if successful, None otherwise
    """
    orchestrator = TeamConsensusOrchestrator()
    return orchestrator.orchestrate_team_evaluation(
        proposal_id=proposal_id,
        auto_generate_report=generate_report,
        auto_notify_admin=notify_admin,
        use_real_ai=use_real_ai,
        user_id=user_id,
    )


if __name__ == "__main__":
    # Test the orchestrator
    print("🧪 Testing Team Consensus Orchestrator...")

    orchestrator = TeamConsensusOrchestrator()

    # Example: Auto-evaluate proposal #1
    # discussion_id = orchestrator.orchestrate_team_evaluation(
    #     proposal_id=1,
    #     auto_generate_report=True,
    #     auto_notify_admin=True
    # )
    #
    # if discussion_id:
    #     print(f"\n✅ SUCCESS: Team evaluation complete")
    #     print(f"   View discussion #{discussion_id} for full details")
    # else:
    #     print(f"\n❌ FAILED: Team evaluation did not complete")
