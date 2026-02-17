"""
Improvement Conversation Engine - Claude Code Style
Fluid conversation for code improvements with automatic proposal creation and escalation

Author: A.R.C.H.I.E.
Date: 2026-01-02
Purpose: Claude Code-style interaction for improvements with smart escalation to contractors
"""

import os
import sys
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_v2.database import get_db
from ai_bridge.improvement_chat import chat_about_improvements
from ai_bridge.team_consensus_orchestrator import TeamConsensusOrchestrator


class ImprovementConversationEngine:
    """
    Claude Code-style conversation engine for improvements

    Features:
    - Natural language improvement detection
    - Automatic proposal creation
    - Code diff generation and preview
    - Step-by-step implementation guidance
    - 3-attempt retry with automatic contractor escalation
    """

    def __init__(self):
        self.orchestrator = TeamConsensusOrchestrator()

    def process_message(
        self, user_message: str, user_id: int, conversation_history: List[Dict] = None
    ) -> Dict:
        """
        Process a user message and determine the appropriate action

        Returns:
            {
                'success': bool,
                'action': str,  # 'conversation', 'create_proposal', 'show_diff', 'apply_changes'
                'response': str,
                'proposal_id': int (optional),
                'proposal_data': dict (optional),
                'code_diff': str (optional),
                'next_steps': list (optional)
            }
        """
        try:
            # Step 1: Detect improvement intent
            intent = self._detect_improvement_intent(user_message)

            if intent["is_improvement"]:
                # Step 2: Use improvement_chat to create/discuss proposal
                chat_result = chat_about_improvements(
                    user_message=user_message,
                    user_id=user_id,
                    auto_create_proposal=True,  # Enable auto-creation
                )

                if chat_result.get("proposal_created"):
                    # Step 3: Check if we should auto-start team evaluation
                    proposal_id = chat_result["proposal_id"]

                    # Get proposal details
                    proposal = self._get_proposal(proposal_id)

                    # Generate Claude Code-style response
                    response = self._format_proposal_created_response(
                        proposal=proposal, chat_response=chat_result.get("response", "")
                    )

                    # Step 4: Automatically start team evaluation for collaborative review
                    if proposal.get("collaboration_enabled"):
                        print(
                            f"🤖 Auto-starting team evaluation for proposal #{proposal_id}..."
                        )
                        discussion_id = self.orchestrator.orchestrate_team_evaluation(
                            proposal_id=proposal_id,
                            auto_generate_report=True,
                            auto_notify_admin=False,  # Don't notify, this is in-conversation
                        )

                        if discussion_id:
                            response += f"\n\n🤖 **Team Review Started**\n"
                            response += f"I've asked the team to review this. Discussion #{discussion_id} is now active."

                    return {
                        "success": True,
                        "action": "create_proposal",
                        "response": response,
                        "proposal_id": proposal_id,
                        "proposal_data": proposal,
                        "next_steps": self._get_next_steps(proposal),
                    }
                else:
                    # Just conversation about improvements
                    return {
                        "success": True,
                        "action": "conversation",
                        "response": chat_result.get(
                            "response", "How can I help with improvements?"
                        ),
                    }
            else:
                # Regular conversation
                return {
                    "success": True,
                    "action": "conversation",
                    "response": self._general_response(user_message),
                }

        except Exception as e:
            print(f"Error in process_message: {e}")
            import traceback

            traceback.print_exc()
            return {
                "success": False,
                "action": "error",
                "response": f"I encountered an error: {str(e)}",
            }

    def retry_with_escalation(self, proposal_id: int, user_id: int) -> Dict:
        """
        Retry a failed proposal with automatic escalation to contractors after 3 attempts

        Returns:
            {
                'success': bool,
                'escalated': bool,
                'attempt_number': int,
                'assigned_agent': str,
                'agent_type': str,  # 'internal' or 'contract'
                'response': str
            }
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Get proposal and current retry count
            cur.execute(
                """
                SELECT id, title, retry_count, assigned_agent_id, status
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                return {
                    "success": False,
                    "response": f"Proposal #{proposal_id} not found",
                }

            current_retry_count = proposal[2] or 0
            new_retry_count = current_retry_count + 1

            # Determine if we should escalate
            should_escalate = new_retry_count >= 3

            if should_escalate:
                # ESCALATE TO CONTRACTOR - Claude Code Level 3
                print(f"🚀 ESCALATING to contractor after {new_retry_count} attempts")

                # Find Claude Code Developer - Level 3 (ID 33)
                cur.execute("""
                    SELECT id, name, worker_type, tier
                    FROM agents
                    WHERE name LIKE '%Claude Code%' AND tier = 3 AND worker_type = 'contract'
                    LIMIT 1
                """)

                contractor = cur.fetchone()

                if contractor:
                    contractor_id = contractor[0]
                    contractor_name = contractor[1]

                    # Update proposal with contractor assignment
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET assigned_agent_id = %s,
                            retry_count = %s,
                            status = 'escalated',
                            escalated_at = NOW(),
                            escalated_to_contractor = TRUE
                        WHERE id = %s
                    """,
                        (contractor_id, new_retry_count, proposal_id),
                    )

                    conn.commit()

                    # Create escalation notification
                    try:
                        cur.execute(
                            """
                            INSERT INTO notifications (
                                user_id, type, title, message, priority, action_url
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                            (
                                user_id,
                                "urgent",
                                f"Proposal #{proposal_id} Escalated to Level 3 Support",
                                f"{contractor_name} has been assigned after {new_retry_count} attempts. This will use paid API credits.",
                                "urgent",
                                f"/tools/admin#improvements-proposal-{proposal_id}",
                            ),
                        )
                        conn.commit()
                    except Exception as e:
                        print(f"Warning: Could not create notification: {e}")

                    response = f"""
🚀 **Escalated to Level 3 Support**

After {new_retry_count} attempts with internal agents, I'm escalating this to **{contractor_name}** (Tier {contractor[3]}).

⚠️ **Note**: This uses paid API credits (contractor).

**What happens next:**
1. {contractor_name} will review with advanced capabilities
2. You'll receive updates as work progresses
3. Higher success rate expected with specialist support

Would you like me to brief {contractor_name} on the context?
                    """

                    cur.close()
                    conn.close()

                    return {
                        "success": True,
                        "escalated": True,
                        "attempt_number": new_retry_count,
                        "assigned_agent": contractor_name,
                        "agent_type": "contract",
                        "agent_id": contractor_id,
                        "response": response,
                    }
                else:
                    # No contractor found, use best available internal
                    print(
                        "⚠️ No Claude Code contractor found, using best internal agent"
                    )
                    should_escalate = False

            if not should_escalate:
                # Use internal agents (attempts 1-2)
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET retry_count = %s,
                        status = 'pending',
                        last_retry_at = NOW()
                    WHERE id = %s
                """,
                    (new_retry_count, proposal_id),
                )

                conn.commit()

                # Restart team evaluation
                discussion_id = self.orchestrator.orchestrate_team_evaluation(
                    proposal_id=proposal_id,
                    auto_generate_report=True,
                    auto_notify_admin=True,
                )

                response = f"""
🔄 **Retry Attempt #{new_retry_count}**

I've reset the proposal and started a fresh team evaluation (Discussion #{discussion_id}).

**Internal team assigned** (no additional cost)

⚠️ **Note**: If this fails again, attempt #{new_retry_count + 1} will escalate to Level 3 contractor support.

The team is reviewing now. I'll keep you updated!
                """

                cur.close()
                conn.close()

                return {
                    "success": True,
                    "escalated": False,
                    "attempt_number": new_retry_count,
                    "assigned_agent": "Internal Team",
                    "agent_type": "internal",
                    "response": response,
                }

        except Exception as e:
            print(f"Error in retry_with_escalation: {e}")
            import traceback

            traceback.print_exc()
            return {"success": False, "response": f"Error during retry: {str(e)}"}

    def _detect_improvement_intent(self, message: str) -> Dict:
        """Detect if message is about improvements"""
        improvement_keywords = [
            "improve",
            "optimize",
            "enhance",
            "fix",
            "bug",
            "issue",
            "should",
            "could",
            "better",
            "faster",
            "refactor",
            "add feature",
            "implement",
            "change",
            "update",
            "modify",
            "performance",
            "security",
            "error",
            "problem",
        ]

        message_lower = message.lower()

        # Check for improvement keywords
        has_keyword = any(keyword in message_lower for keyword in improvement_keywords)

        # Check for code blocks (indication of code-related discussion)
        has_code = "```" in message or "code" in message_lower

        return {
            "is_improvement": has_keyword or has_code,
            "confidence": 0.8 if has_keyword else 0.5,
        }

    def _get_proposal(self, proposal_id: int) -> Optional[Dict]:
        """Get proposal details"""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                SELECT id, title, category, description, status, priority,
                       risk_level, collaboration_enabled, retry_count
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )

            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                return {
                    "id": row[0],
                    "title": row[1],
                    "category": row[2],
                    "description": row[3],
                    "status": row[4],
                    "priority": row[5],
                    "risk_level": row[6],
                    "collaboration_enabled": row[7],
                    "retry_count": row[8] or 0,
                }
            return None
        except Exception as e:
            print(f"Error getting proposal: {e}")
            return None

    def _format_proposal_created_response(
        self, proposal: Dict, chat_response: str
    ) -> str:
        """Format a Claude Code-style response for proposal creation"""
        return f"""
✨ **Proposal Created: #{proposal['id']}**

**{proposal['title']}**

{chat_response}

**Details:**
- **Category**: {proposal['category']}
- **Priority**: {proposal['priority']}
- **Risk**: {proposal['risk_level']}
- **Retry Count**: {proposal['retry_count']}/3 (escalates to Level 3 contractor at 3)

{self._get_risk_warning(proposal)}
        """.strip()

    def _get_risk_warning(self, proposal: Dict) -> str:
        """Get risk warning based on proposal risk level"""
        if proposal["risk_level"] == "high":
            return "\n⚠️ **High Risk**: This will require manual approval and extensive testing."
        elif proposal["risk_level"] == "critical":
            return "\n🚨 **Critical Risk**: Backup will be created automatically. Rollback plan required."
        return ""

    def _get_next_steps(self, proposal: Dict) -> List[str]:
        """Get next steps for the proposal"""
        steps = []

        if proposal["status"] == "pending":
            steps.append("⏳ Awaiting team review")

        if proposal["collaboration_enabled"]:
            steps.append("🤝 Team collaboration enabled - multiple agents will review")

        if proposal["priority"] == "critical":
            steps.append("🚨 High priority - will be reviewed immediately")

        steps.append("🧪 Will be tested in sandbox before deployment")
        steps.append("💾 Automatic backup before implementation")

        return steps

    def _general_response(self, message: str) -> str:
        """Generate a general conversational response"""
        return """
I'm here to help with code improvements! I can:

- 💬 **Discuss improvements** naturally - just tell me what you're thinking
- ✨ **Create proposals** automatically from our conversation
- 🔍 **Review existing code** and suggest optimizations
- 🧪 **Test changes** in a safe sandbox environment
- 🚀 **Deploy improvements** with automatic backups
- 📊 **Track progress** with team collaboration

**Smart Escalation**:
- Attempts 1-2: Internal team (FREE - Ollama models)
- Attempt 3+: Level 3 contractor support (Claude Code - Paid API)

What would you like to improve?
        """.strip()


# Convenience functions for API usage
def process_improvement_message(
    user_message: str, user_id: int, conversation_history: List[Dict] = None
) -> Dict:
    """Process a message about improvements"""
    engine = ImprovementConversationEngine()
    return engine.process_message(user_message, user_id, conversation_history)


def retry_proposal_with_escalation(proposal_id: int, user_id: int) -> Dict:
    """Retry a proposal with automatic contractor escalation after 3 attempts"""
    engine = ImprovementConversationEngine()
    return engine.retry_with_escalation(proposal_id, user_id)
