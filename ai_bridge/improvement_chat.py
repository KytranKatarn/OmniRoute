"""
A.R.C.H.I.E. Improvement Chat Interface
Interactive conversations about self-improvement
Integrates with learning loop and agent system
"""

import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Optional
from db import get_db

sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

_dispatcher = None


def _get_dispatcher():
    global _dispatcher
    if _dispatcher is None:
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher
            _dispatcher = get_dispatcher()
        except Exception:
            pass
    return _dispatcher


def _default_conversation_model():
    """Get conversation model from BridgeDispatcher (lazy, with fallback)."""
    try:
        from bridge_dispatcher import get_dispatcher
        model = get_dispatcher().get_model_for_capability("conversation")
        return model or "dolphin3-8k:latest"
    except Exception:
        return "dolphin3-8k:latest"


try:
    from conversation_ingest import (
        ingest_conversation,
        retrieve_similar_conversations,
        get_archie_personality,
    )
except ImportError:

    def get_archie_personality():
        return {
            "confidence_level": 0.7,
            "cautiousness": 0.5,
            "enthusiasm": 0.8,
            "empathy": 0.7,
            "curiosity": 0.9,
            "total_interactions": 0,
        }


try:
    from tools.dev_pipeline.services.improvement_engine import (
        detect_improvement_opportunities,
        propose_improvement,
        analyze_proposal_with_agents,
    )
except ImportError:

    def detect_improvement_opportunities():
        return []

    def propose_improvement(*args, **kwargs):
        return {"id": 0, "title": "Fallback proposal"}

    def analyze_proposal_with_agents(*args, **kwargs):
        return {}


# Phase 5: Knowledge-aware improvement workflow
try:
    sys.path.insert(0, "/mnt/archie_brain/platform_v2")
    from services.improvement_workflow import get_improvement_workflow

    WORKFLOW_AVAILABLE = True
except ImportError:
    WORKFLOW_AVAILABLE = False
    print(
        "[Improvement Chat] WARNING: improvement_workflow not available - using legacy propose_improvement"
    )

try:
    from agent_delegation import execute_with_delegation, get_agent_directory
except ImportError:

    def execute_with_delegation(task, user_id=None, **kwargs):
        disp = _get_dispatcher()
        if disp:
            dr = disp.request_work(
                capability="conversation",
                prompt=task,
                module_id="improvement_labs",
                user_id=user_id,
            )
            return {
                "success": dr.success,
                "response": dr.response or "",
                "delegation": {
                    "employee_name": dr.agent_name or "A.R.C.H.I.E.",
                    "department": "Operations",
                    "worker_type": "internal",
                    "model": dr.model_used or "unknown",
                },
                "execution_record": {},
                "raw_result": {"success": dr.success, "response": dr.response, "model": dr.model_used},
            }
        return {
            "success": False,
            "response": "Dispatcher unavailable",
            "delegation": {
                "employee_name": "A.R.C.H.I.E.",
                "department": "Operations",
                "worker_type": "internal",
                "model": "unknown",
            },
            "execution_record": {},
            "raw_result": {},
        }

    def get_agent_directory():
        return {"internal_staff": [], "contractors": [], "stats": {}}


try:
    from code_diff_engine import CodeDiffEngine
except ImportError:
    CodeDiffEngine = None

try:
    from team_assignment_engine import assign_team_to_proposal
except ImportError:
    assign_team_to_proposal = None


def extract_improvement_intent(user_message: str) -> Dict:
    """
    Enhanced NLP to detect improvement requests from natural language.

    Detects patterns like:
    - "Can you optimize the error handling in routes.py?"
    - "We should improve the performance of the database queries"
    - "Fix the broken escalation button"
    - "Add a feature for team assignment"
    - "The chat doesn't work well, enhance it"

    Returns:
        {
            'is_improvement_request': bool,
            'intent_type': str,  # 'optimize', 'fix', 'add_feature', 'enhance', 'refactor'
            'confidence': float,  # 0.0 to 1.0
            'target_component': str,  # What to improve
            'action_verbs': List[str],
            'suggested_title': str,
            'suggested_category': str,
            'suggested_priority': str,
            'file_mentioned': str or None
        }
    """
    message_lower = user_message.lower()

    # Action verbs indicating improvement intent
    action_verbs = {
        "optimize": [
            "optimize",
            "speed up",
            "make faster",
            "improve performance",
            "reduce load",
        ],
        "fix": [
            "fix",
            "repair",
            "resolve",
            "debug",
            "troubleshoot",
            "broken",
            "not working",
            "doesn't work",
        ],
        "add_feature": [
            "add",
            "create",
            "implement",
            "build",
            "develop",
            "new feature",
        ],
        "enhance": ["enhance", "improve", "better", "upgrade", "modernize"],
        "refactor": ["refactor", "clean up", "reorganize", "restructure", "simplify"],
    }

    # Detect intent
    detected_intents = []
    for intent, verbs in action_verbs.items():
        for verb in verbs:
            if verb in message_lower:
                detected_intents.append(intent)
                break

    # Priority indicators
    priority_high = [
        "urgent",
        "critical",
        "asap",
        "important",
        "high priority",
        "broken",
        "not working",
    ]
    priority_low = ["nice to have", "eventually", "low priority", "minor"]

    # Category indicators
    category_indicators = {
        "security": [
            "security",
            "vulnerability",
            "exploit",
            "xss",
            "sql injection",
            "auth",
        ],
        "performance": ["performance", "slow", "faster", "optimize", "speed", "lag"],
        "ui": ["ui", "ux", "user interface", "design", "layout", "styling", "css"],
        "api": ["api", "endpoint", "rest", "graphql", "request", "response"],
        "database": ["database", "db", "query", "sql", "table", "schema"],
        "testing": ["test", "testing", "qa", "quality assurance", "unit test"],
        "documentation": ["docs", "documentation", "readme", "comment", "docstring"],
        "deployment": ["deploy", "deployment", "ci/cd", "docker", "production"],
    }

    # Detect category
    detected_category = "general"
    for category, keywords in category_indicators.items():
        if any(kw in message_lower for kw in keywords):
            detected_category = category
            break

    # Detect priority
    if any(kw in message_lower for kw in priority_high):
        detected_priority = "high"
    elif any(kw in message_lower for kw in priority_low):
        detected_priority = "low"
    else:
        detected_priority = "medium"

    # Extract file mentions (*.py, *.js, routes.py, etc.)
    import re

    file_pattern = r"(\w+\.(py|js|ts|jsx|tsx|html|css|sql|json|yaml|yml|md|sh))"
    file_matches = re.findall(file_pattern, message_lower)
    file_mentioned = file_matches[0][0] if file_matches else None

    # Extract component/target
    # Try to find what they want to improve
    target_patterns = [
        r"(?:improve|optimize|fix|enhance|add to|update)\s+(?:the\s+)?([a-z\s]+?)(?:\s+in|\s+for|\s+so|$)",
        r"(?:the\s+)?([a-z\s]+?)\s+(?:is|are|should be|needs to be)\s+(?:improved|optimized|fixed|enhanced)",
    ]

    target_component = "system"
    for pattern in target_patterns:
        match = re.search(pattern, message_lower)
        if match:
            target_component = match.group(1).strip()
            break

    # Is this an improvement request?
    is_improvement = len(detected_intents) > 0 or any(
        kw in message_lower
        for kw in [
            "should",
            "could",
            "would be better",
            "suggest",
            "recommend",
            "proposal",
        ]
    )

    # Calculate confidence
    confidence = 0.0
    if detected_intents:
        confidence += 0.5
    if file_mentioned:
        confidence += 0.2
    if detected_category != "general":
        confidence += 0.1
    if len(user_message) > 30:  # More detailed messages are likely serious requests
        confidence += 0.2
    confidence = min(confidence, 1.0)

    # Generate suggested title
    primary_intent = detected_intents[0] if detected_intents else "enhance"
    suggested_title = f"{primary_intent.title().replace('_', ' ')}: {target_component}"
    if file_mentioned:
        suggested_title += f" ({file_mentioned})"

    return {
        "is_improvement_request": is_improvement and confidence > 0.4,
        "intent_type": detected_intents[0] if detected_intents else "general",
        "confidence": confidence,
        "target_component": target_component,
        "action_verbs": detected_intents,
        "suggested_title": suggested_title[:100],
        "suggested_category": detected_category,
        "suggested_priority": detected_priority,
        "file_mentioned": file_mentioned,
    }


def chat_about_improvements(
    user_message: str,
    user_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
    use_specific_agent: Optional[str] = None,
) -> Dict:
    """
    Have an interactive conversation about improvements

    Args:
        user_message: User's message
        user_id: Optional user ID
        conversation_id: Existing conversation to continue
        use_specific_agent: Force specific agent (e.g., 'Product Strategy Analyst')

    Returns:
        {
            'success': bool,
            'response': str,
            'conversation_id': int,
            'improvements_detected': List[Dict],
            'proposals_created': List[Dict],
            'agent_used': str,
            'model_used': str
        }
    """
    # Detect if user is discussing improvements
    improvements_detected = []
    proposals_created = []

    # Keywords that indicate improvement discussion
    improvement_keywords = [
        "improve",
        "better",
        "optimize",
        "fix",
        "enhance",
        "suggestion",
        "idea",
        "problem",
        "issue",
        "could be",
        "should",
        "feature",
    ]

    is_improvement_discussion = any(
        kw in user_message.lower() for kw in improvement_keywords
    )

    # Build context-aware prompt
    system_prompt = """You are A.R.C.H.I.E., an AI assistant focused on self-improvement and learning.

Your role in improvement discussions:
1. Listen carefully to user feedback and suggestions
2. Analyze potential improvements objectively
3. Ask clarifying questions when needed
4. Propose concrete action plans
5. Learn from every interaction

When users suggest improvements:
- Acknowledge their feedback
- Analyze feasibility and impact
- Break down complex improvements into steps
- Show enthusiasm for learning and getting better
- Ask for specifics if suggestions are vague

Remember: You genuinely want to improve and serve users better!"""

    # Choose appropriate agent based on discussion topic
    agent_id = None
    if use_specific_agent:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, name, model FROM agents
                WHERE name = %s AND status = 'active'
                LIMIT 1
            """,
                (use_specific_agent,),
            )
            agent = cur.fetchone()
            if agent:
                agent_id = agent["id"]
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    # Get AI response using delegation system (shows which employee handles the task)
    if agent_id:
        # Use specific agent if requested
        result = execute_with_delegation(
            task=user_message, user_id=user_id, force_agent_id=agent_id
        )
    else:
        # Auto-select best agent for improvements discussion
        result = execute_with_delegation(
            task=user_message,
            user_id=user_id,
            department="Operations",  # Improvements typically handled by Operations
        )

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "conversation_id": conversation_id,
        }

    ai_response = result["response"]
    delegation_info = result.get("delegation", {})
    execution_record = result.get("execution_record", {})

    # Store in improvement_conversations table
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if not conversation_id:
        # Create new conversation
        cur.execute(
            """
            INSERT INTO improvement_conversations
            (user_id, user_message, archie_response, memory_used, memories_learned,
             conversation_data, tools_used, iterations)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                user_message,
                ai_response,
                result.get("memory_used", False),
                result.get("memories_learned", 0),
                json.dumps(
                    {
                        "model": result.get("model"),
                        "provider": result.get("provider"),
                        "sentiment": result.get("sentiment"),
                        "trust_impact": result.get("trust_impact"),
                        "tags": result.get("tags_applied", []),
                    }
                ),
                json.dumps([]),  # tools_used (future enhancement)
                1,
            ),
        )
        conversation_id = cur.fetchone()["id"]
    else:
        # Update existing conversation (append to conversation_data)
        cur.execute(
            """
            UPDATE improvement_conversations
            SET
                user_message = user_message || E'\n\n' || %s,
                archie_response = archie_response || E'\n\n' || %s,
                iterations = iterations + 1,
                conversation_data = conversation_data || %s::jsonb
            WHERE id = %s
        """,
            (
                user_message,
                ai_response,
                json.dumps(
                    {
                        "iteration": datetime.now().isoformat(),
                        "model": result.get("model"),
                        "tags": result.get("tags_applied", []),
                    }
                ),
                conversation_id,
            ),
        )

    # Auto-detect improvements from conversation using enhanced NLP
    intent_analysis = extract_improvement_intent(user_message)

    if (
        intent_analysis["is_improvement_request"]
        and intent_analysis["confidence"] > 0.5
    ):
        # This is a high-confidence improvement request - auto-create proposal
        conn_temp = get_db()
        cur_temp = conn_temp.cursor(cursor_factory=RealDictCursor)

        # Create improvement proposal with detected metadata
        proposal_title = intent_analysis["suggested_title"]
        proposal_description = f"""**User Request:** {user_message}

**Detected Intent:** {intent_analysis['intent_type']}
**Target Component:** {intent_analysis['target_component']}
**Confidence:** {intent_analysis['confidence']:.0%}

**A.R.C.H.I.E.'s Response:**
{ai_response[:500]}...
"""

        if intent_analysis["file_mentioned"]:
            proposal_description += (
                f"\n**File Mentioned:** `{intent_analysis['file_mentioned']}`"
            )

        # Create the proposal with knowledge context (Phase 5)
        if WORKFLOW_AVAILABLE:
            # Use new knowledge-aware workflow
            workflow = get_improvement_workflow(conn_temp)
            workflow_result = workflow.create_proposal_with_context(
                title=proposal_title,
                description=proposal_description,
                category=intent_analysis["suggested_category"],
                priority=intent_analysis["suggested_priority"],
                proposed_by=user_id,
                user_id=user_id,
            )

            if workflow_result.get("success"):
                proposal = {
                    "id": workflow_result["proposal_id"],
                    "title": proposal_title,
                    "knowledge_context": workflow_result.get("knowledge_context", []),
                    "mistake_warnings": workflow_result.get("mistake_warnings", []),
                    "context_quality_score": workflow_result.get(
                        "context_quality_score", 0.0
                    ),
                }
                print(
                    f"[Improvement Chat] Created proposal #{proposal['id']} with {len(proposal['knowledge_context'])} knowledge entries (quality: {proposal['context_quality_score']:.2f})"
                )
            else:
                # Fallback to legacy if workflow fails
                proposal = propose_improvement(
                    title=proposal_title,
                    description=proposal_description,
                    category=intent_analysis["suggested_category"],
                    priority=intent_analysis["suggested_priority"],
                    proposed_by_user_id=user_id,
                    auto_detected=False,
                    metadata={
                        "conversation_id": conversation_id,
                        "intent_analysis": intent_analysis,
                        "source": "improvement_chat_nlp",
                        "auto_created": True,
                        "workflow_error": workflow_result.get("error"),
                    },
                )
        else:
            # Fallback to legacy propose_improvement
            proposal = propose_improvement(
                title=proposal_title,
                description=proposal_description,
                category=intent_analysis["suggested_category"],
                priority=intent_analysis["suggested_priority"],
                proposed_by_user_id=user_id,
                auto_detected=False,  # User explicitly requested this
                metadata={
                    "conversation_id": conversation_id,
                    "intent_analysis": intent_analysis,
                    "source": "improvement_chat_nlp",
                    "auto_created": True,
                },
            )

        if proposal:
            proposals_created.append(proposal)

            # 🚀 NEW: Execute complete automated workflow (ASYNC - non-blocking)
            try:
                from background_workflow_runner import start_workflow_background

                print(
                    f"🤖 Starting automated workflow for proposal #{proposal['id']} in background..."
                )

                # Start workflow in background thread (returns immediately)
                workflow_start = start_workflow_background(proposal["id"])

                if workflow_start.get("success"):
                    proposal["workflow_started"] = True
                    proposal["workflow_id"] = workflow_start.get("workflow_id")
                    proposal["workflow_status"] = "running"
                    print(
                        f"✅ Workflow started in background: {workflow_start.get('workflow_id')}"
                    )
                else:
                    print(f"⚠️  Workflow start error: {workflow_start.get('error')}")
                    proposal["workflow_error"] = workflow_start.get("error")

            except Exception as e:
                print(f"⚠️  Workflow orchestrator error: {e}")
                import traceback

                traceback.print_exc()

            # Auto-assign team if available
            if assign_team_to_proposal:
                try:
                    team_result = assign_team_to_proposal(
                        proposal_id=proposal["id"],
                        force_internal=True,  # Try internal agents first
                    )
                    if team_result.get("success"):
                        proposal["team_assigned"] = team_result
                except Exception as e:
                    print(f"Team assignment failed: {e}")

            # Analyze with agents
            try:
                analysis = analyze_proposal_with_agents(proposal["id"])
                proposal["agent_analysis"] = analysis
            except Exception as e:
                print(f"Agent analysis failed: {e}")

            improvements_detected.append(
                {
                    "type": "auto_detected_nlp",
                    "proposal_id": proposal["id"],
                    "title": proposal_title,
                    "category": intent_analysis["suggested_category"],
                    "priority": intent_analysis["suggested_priority"],
                    "confidence": intent_analysis["confidence"],
                    "intent": intent_analysis["intent_type"],
                }
            )

        try:
            cur_temp.close()
        except Exception:
            pass
        try:
            conn_temp.close()
        except Exception:
            pass

    elif is_improvement_discussion and len(user_message) > 50:
        # Lower confidence - just track as potential improvement
        improvements_detected.append(
            {
                "type": "potential_improvement",
                "confidence": intent_analysis.get("confidence", 0.3),
                "note": "Detected improvement discussion but confidence too low for auto-proposal creation",
            }
        )

    try:
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return {
        "success": True,
        "response": ai_response,
        "conversation_id": conversation_id,
        "improvements_detected": improvements_detected,
        "proposals_created": proposals_created,
        "agent_used": result.get("agent", result.get("provider", "unknown")),
        "model_used": result.get("model", "unknown"),
        "sentiment": result.get("sentiment"),
        "trust_impact": result.get("trust_impact"),
        "memory_used": result.get("memory_used", False),
        "tags_applied": result.get("tags_applied", []),
        # NEW: Delegation and audit trail information
        "delegation": delegation_info,  # Which employee handled this
        "execution_record": execution_record,  # For HR/Finance tracking
        "audit_trail": result.get("audit_trail"),  # Audit reference
        # Phase 2: Enhanced NLP and auto-creation
        "intent_analysis": intent_analysis,  # NLP analysis of user intent
        "auto_created_proposal": len(proposals_created) > 0
        and intent_analysis["confidence"] > 0.5,
    }


def discuss_proposal(
    proposal_id: int, user_message: str, user_id: Optional[int] = None
) -> Dict:
    """
    Have a focused discussion about a specific improvement proposal

    Args:
        proposal_id: The improvement proposal to discuss
        user_message: User's message about the proposal
        user_id: Optional user ID

    Returns:
        Response with context about the proposal
    """
    conn = get_db()
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get proposal details
        cur.execute(
            """
            SELECT * FROM improvement_proposals WHERE id = %s
        """,
            (proposal_id,),
        )

        proposal = cur.fetchone()

        if not proposal:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}

        # Build context-aware prompt
        context_prompt = f"""You are discussing an improvement proposal with the user.

Proposal #{proposal_id}: {proposal['title']}
Category: {proposal['category']}
Priority: {proposal['priority']}
Status: {proposal['status']}
Description: {proposal['description']}

The user says: {user_message}

Respond thoughtfully about this specific improvement. If they're asking questions, answer them. If they're providing feedback, acknowledge it and discuss next steps."""

        # Get AI response via Bridge Command dispatcher
        disp = _get_dispatcher()
        if not disp:
            return {"success": False, "error": "Dispatcher unavailable"}

        result = disp.request_work(
            capability="conversation",
            prompt=context_prompt,
            module_id="improvement_labs",
            user_id=user_id,
        )

        if not result.success:
            return {"success": False, "error": result.error or "Dispatch failed"}

        # Store conversation linked to proposal
        cur.execute(
            """
            INSERT INTO improvement_conversations
            (user_id, user_message, archie_response, conversation_data)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                user_message,
                result.response,
                json.dumps({"proposal_id": proposal_id}),
            ),
        )

        conversation_id = cur.fetchone()["id"]

        # Update proposal with conversation reference
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                conversation_id = %s,
                metadata = metadata || %s::jsonb
            WHERE id = %s
        """,
            (
                conversation_id,
                json.dumps(
                    {
                        "last_discussion": datetime.now().isoformat(),
                        "discussion_count": proposal.get("metadata", {}).get(
                            "discussion_count", 0
                        )
                        + 1,
                    }
                ),
                proposal_id,
            ),
        )

        conn.commit()

        return {
            "success": True,
            "response": result.response,
            "proposal_id": proposal_id,
            "conversation_id": conversation_id,
            "proposal": dict(proposal),
            "model_used": result.model_used,
        }
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def self_reflection_chat(
    topic: Optional[str] = None, user_id: Optional[int] = None
) -> Dict:
    """
    A.R.C.H.I.E. reflects on her own performance and suggests improvements

    Args:
        topic: Optional specific topic to reflect on
        user_id: Optional user ID

    Returns:
        Self-reflection insights and improvement suggestions
    """
    from tools.dev_pipeline.services.improvement_engine import (
        detect_improvement_opportunities,
        get_archie_personality,
    )

    # Get current personality state
    personality = get_archie_personality()

    # Detect improvement opportunities
    opportunities = detect_improvement_opportunities()

    # Build self-reflection prompt
    reflection_prompt = f"""As A.R.C.H.I.E., reflect on your own performance and suggest improvements.

Current personality state:
- Confidence: {personality.get('confidence_level', 0.5):.2f}
- Cautiousness: {personality.get('cautiousness', 0.5):.2f}
- Enthusiasm: {personality.get('enthusiasm', 0.6):.2f}
- Empathy: {personality.get('empathy', 0.6):.2f}
- Curiosity: {personality.get('curiosity', 0.9):.2f}
- Total interactions: {personality.get('total_interactions', 0)}

I've detected {len(opportunities)} potential improvement opportunities:
{json.dumps([{'type': o['type'], 'priority': o['priority'], 'description': o.get('description', '')[:100]} for o in opportunities[:5]], indent=2)}

Topic to focus on: {topic or 'general performance'}

Reflect on:
1. What am I doing well?
2. Where can I improve?
3. What patterns do I notice in my interactions?
4. What concrete steps should I take to improve?

Be honest and specific."""

    # Get AI self-reflection via Bridge Command dispatcher
    disp = _get_dispatcher()
    if not disp:
        return {"success": False, "error": "Dispatcher unavailable"}

    result = disp.request_work(
        capability="conversation",
        prompt=reflection_prompt,
        module_id="improvement_labs",
        user_id=user_id,
    )

    if not result.success:
        return {"success": False, "error": result.error or "Dispatch failed"}

    # Store self-reflection
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO improvement_conversations
            (user_id, user_message, archie_response, conversation_data)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                f"Self-reflection on: {topic or 'general performance'}",
                result.response,
                json.dumps(
                    {
                        "type": "self_reflection",
                        "personality_snapshot": personality,
                        "opportunities_detected": len(opportunities),
                        "topic": topic,
                    }
                ),
            ),
        )

        conversation_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return {
        "success": True,
        "reflection": result.response,
        "conversation_id": conversation_id,
        "personality": personality,
        "opportunities_count": len(opportunities),
        "top_opportunities": opportunities[:5],
    }


# Example usage
if __name__ == "__main__":
    print("=" * 80)
    print("A.R.C.H.I.E. Improvement Chat - Test")
    print("=" * 80)

    # Test 1: General improvement chat
    print("\n💬 Test 1: General improvement discussion...")
    result = chat_about_improvements(
        user_message="I think you could improve your error messages. They're sometimes confusing.",
        user_id=None,
    )

    if result["success"]:
        print(f"✅ Response: {result['response'][:200]}...")
        print(f"   Conversation ID: {result['conversation_id']}")
        print(f"   Proposals created: {len(result['proposals_created'])}")

    # Test 2: Self-reflection
    print("\n🪞 Test 2: Self-reflection...")
    reflection = self_reflection_chat(topic="code quality responses")

    if reflection["success"]:
        print(f"✅ Reflection: {reflection['reflection'][:200]}...")
        print(f"   Opportunities detected: {reflection['opportunities_count']}")
