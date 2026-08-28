"""
A.R.C.H.I.E. Self-Improvement Engine
Analyzes conversations, detects patterns, and proposes improvements
Uses the learning loop, agents, and automation to continuously improve
"""

import os
from database import _get_db_password
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

try:
    from conversation_ingest import (
        retrieve_similar_conversations,
        get_archie_personality,
    )
except ImportError:

    def retrieve_similar_conversations(*args, **kwargs):
        return []

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
    from emotional_intelligence import analyze_sentiment, analyze_trust_impact
except ImportError:

    def analyze_sentiment(text):
        return {"sentiment": "neutral", "confidence": 0.5}

    def analyze_trust_impact(text):
        return 0.0


try:
    from ai_bridge.auto_tagger import analyze_content
except ImportError:

    def analyze_content(text):
        return {"tags": [], "categories": []}


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _get_db():
    """Get DB connection using platform pattern (with fallback for standalone execution)."""
    try:
        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from database import get_db_cursor

        return get_db_cursor
    except ImportError:
        return get_db


def detect_improvement_opportunities() -> List[Dict]:
    """
    Analyze consciousness database to detect improvement opportunities

    Detects:
    - Repeated errors
    - Low trust interactions
    - Frequently asked questions (optimization targets)
    - Knowledge gaps
    - Performance issues

    Returns:
        List of improvement opportunities
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        opportunities = []

        # 1. Detect repeated errors (low trust, negative sentiment)
        cur.execute(
            """
            SELECT
                tags,
                COUNT(*) as occurrence_count,
                AVG((metadata->>'trust_impact')::float) as avg_trust,
                AVG(importance_score) as avg_importance,
                STRING_AGG(content::text, ' | ' ORDER BY created_at DESC) as sample_conversations
            FROM long_term_memory
            WHERE memory_type = 'conversation'
            AND metadata->>'sentiment' = 'negative'
            AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY tags
            HAVING COUNT(*) >= 3  -- At least 3 occurrences
            AND AVG((metadata->>'trust_impact')::float) < -0.1
            ORDER BY occurrence_count DESC
            LIMIT 10;
        """
        )

        for row in cur.fetchall():
            opportunities.append(
                {
                    "type": "repeated_error",
                    "priority": "high",
                    "tags": row["tags"],
                    "occurrence_count": row["occurrence_count"],
                    "avg_trust_impact": row["avg_trust"],
                    "description": f"Repeated negative interactions with tags: {', '.join(row['tags'][:3])}. Occurred {row['occurrence_count']} times.",
                    "suggested_action": "Analyze these conversations to identify the root cause and improve responses.",
                    "category": "quality",
                }
            )

        # 2. Detect frequently asked questions (optimization targets)
        cur.execute(
            """
            SELECT
                unnest(tags) as tag,
                COUNT(*) as question_count,
                AVG(importance_score) as avg_importance
            FROM long_term_memory
            WHERE memory_type = 'conversation'
            AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY tag
            HAVING COUNT(*) >= 5
            ORDER BY question_count DESC
            LIMIT 10;
        """
        )

        for row in cur.fetchall():
            opportunities.append(
                {
                    "type": "frequently_asked",
                    "priority": "medium",
                    "tag": row["tag"],
                    "question_count": row["question_count"],
                    "description": f"Topic '{row['tag']}' asked {row['question_count']} times. Could benefit from optimization.",
                    "suggested_action": "Create specialized knowledge base or FAQ for this topic.",
                    "category": "efficiency",
                }
            )

        # 3. Detect knowledge gaps (questions with low confidence)
        cur.execute(
            """
            SELECT
                tags,
                COUNT(*) as gap_count,
                AVG(importance_score) as avg_importance,
                content
            FROM long_term_memory
            WHERE memory_type = 'conversation'
            AND metadata->>'user_emotion' IN ('confused', 'frustrated')
            AND created_at > NOW() - INTERVAL '30 days'
            GROUP BY tags, content
            HAVING COUNT(*) >= 2
            ORDER BY gap_count DESC
            LIMIT 5;
        """
        )

        for row in cur.fetchall():
            opportunities.append(
                {
                    "type": "knowledge_gap",
                    "priority": "high",
                    "tags": row["tags"],
                    "gap_count": row["gap_count"],
                    "description": f"Users frequently confused about: {', '.join(row['tags'][:2])}",
                    "suggested_action": "Expand knowledge base or improve explanations for these topics.",
                    "category": "knowledge",
                }
            )

        # 4. Detect underutilized models (agents not being used)
        cur.execute(
            """
            SELECT
                a.name,
                a.department,
                a.model,
                a.worker_type,
                COALESCE(a.last_used, a.created_at) as last_used,
                0 as usage_count
            FROM agents a
            WHERE a.status = 'active'
            AND a.worker_type = 'internal'
            AND (a.last_used IS NULL OR a.last_used < NOW() - INTERVAL '7 days')
            ORDER BY last_used ASC NULLS FIRST
            LIMIT 10;
        """
        )

        for row in cur.fetchall():
            opportunities.append(
                {
                    "type": "underutilized_agent",
                    "priority": "low",
                    "agent_name": row["name"],
                    "department": row["department"],
                    "model": row["model"],
                    "usage_count": row["usage_count"] or 0,
                    "last_used": (row["last_used"].isoformat() if row["last_used"] else "Never"),
                    "description": f"Agent '{row['name']}' ({row['model']}) rarely used. Only {row['usage_count'] or 0} executions.",
                    "suggested_action": "Consider reassigning this agent or promoting its capabilities.",
                    "category": "resource_optimization",
                }
            )

        # 5. Detect personality drift (check if personality needs rebalancing)
        personality = get_archie_personality()

        if personality.get("cautiousness", 0.5) > 0.8:
            opportunities.append(
                {
                    "type": "personality_drift",
                    "priority": "medium",
                    "trait": "cautiousness",
                    "value": personality["cautiousness"],
                    "description": f"Cautiousness level is very high ({personality['cautiousness']:.2f}). A.R.C.H.I.E. may be too hesitant.",
                    "suggested_action": "Balance with more positive interactions or adjust trait calculation.",
                    "category": "personality",
                }
            )

        if personality.get("confidence_level", 0.5) < 0.3:
            opportunities.append(
                {
                    "type": "personality_drift",
                    "priority": "medium",
                    "trait": "confidence",
                    "value": personality["confidence_level"],
                    "description": f"Confidence level is low ({personality['confidence_level']:.2f}). May need more positive reinforcement.",
                    "suggested_action": "Encourage more positive feedback loops or adjust confidence calculation.",
                    "category": "personality",
                }
            )

        cur.close()
    finally:
        conn.close()

    return opportunities


def propose_improvement(
    title: str,
    description: str,
    category: str,
    priority: str = "medium",
    proposed_by_user_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    auto_detected: bool = False,
    metadata: Optional[Dict] = None,
    auto_assign_team: bool = True,
    auto_generate_steps: bool = True,
    auto_generate_diff: bool = False,
    code_changes: Optional[List[Dict]] = None,
) -> Dict:
    """
    Create an improvement proposal with optional team assignment and step generation.

    Args:
        title: Short title for the improvement
        description: Detailed description
        category: Category (quality, efficiency, knowledge, resource_optimization, personality)
        priority: Priority level (low, medium, high, critical)
        proposed_by_user_id: User who proposed (if manual)
        agent_id: Agent that detected this (if auto)
        auto_detected: Whether this was automatically detected
        metadata: Additional metadata
        auto_assign_team: Automatically assign team (default: True) - PHASE 3
        auto_generate_steps: Automatically generate implementation steps (default: True) - PHASE 2
        auto_generate_diff: Automatically generate code diff preview (default: False)
        code_changes: List of file changes for diff generation [{'path': str, 'before': str, 'after': str}]

    Returns:
        Created proposal dict with team and steps info
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        proposal_metadata = {
            "auto_detected": auto_detected,
            "detection_timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            **(metadata or {}),
        }

        # Auto-calculate complexity based on category
        complexity = "medium"
        high_complexity_categories = ["security", "architecture", "database", "performance"]
        low_complexity_categories = ["documentation", "knowledge"]

        if category in high_complexity_categories:
            complexity = "high"
        elif category in low_complexity_categories:
            complexity = "low"

        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, description, category, priority, proposed_by, proposed_at,
             status, metadata, complexity)
            VALUES (%s, %s, %s, %s, %s, NOW(), 'proposed', %s, %s)
            RETURNING id, title, category, priority, status, proposed_at, complexity;
        """,
            (
                title,
                description,
                category,
                priority,
                proposed_by_user_id,
                json.dumps(proposal_metadata),
                complexity,
            ),
        )

        result = dict(cur.fetchone())
        proposal_id = result["id"]

        conn.commit()
        cur.close()
    finally:
        conn.close()

    # PHASE 3: Auto-assign team if enabled
    if auto_assign_team:
        try:
            from team_assignment_engine import assign_team_to_proposal

            team_result = assign_team_to_proposal(
                proposal_id=proposal_id,
                force_internal=True,  # Try internal agents first for cost savings
                user_id=proposed_by_user_id,
            )

            if team_result.get("success"):
                result["team_assigned"] = True
                result["team"] = team_result.get("team", [])
                result["team_size"] = team_result.get("team_size", 0)
                result["internal_count"] = team_result.get("internal_count", 0)
                result["contract_count"] = team_result.get("contract_count", 0)
                print(
                    f"✅ Team assigned to proposal {proposal_id}: {team_result['team_size']} agents ({team_result['internal_count']} internal, {team_result['contract_count']} contract)"
                )
            else:
                result["team_assigned"] = False
                result["team_error"] = team_result.get("error")
                print(f"⚠️  Team assignment failed for proposal {proposal_id}: {team_result.get('error')}")

        except Exception as e:
            print(f"❌ Team assignment exception for proposal {proposal_id}: {e}")
            result["team_assigned"] = False
            result["team_error"] = str(e)

    # PHASE 2: Auto-generate implementation steps if enabled
    if auto_generate_steps:
        try:
            from step_guidance_generator import generate_steps_for_proposal

            steps_result = generate_steps_for_proposal(proposal_id)

            if steps_result:
                result["steps_generated"] = True
                result["total_steps"] = steps_result.get("total_steps", 0)
                result["estimated_time"] = steps_result.get("total_estimated_time", "Unknown")
                print(
                    f"✅ Steps generated for proposal {proposal_id}: {steps_result['total_steps']} steps, ~{steps_result['total_estimated_time']}"
                )
            else:
                result["steps_generated"] = False

        except Exception as e:
            print(f"⚠️  Step generation failed for proposal {proposal_id}: {e}")
            result["steps_generated"] = False
            result["steps_error"] = str(e)

    # PHASE 4: Auto-generate code diff preview if enabled
    if auto_generate_diff and code_changes:
        try:
            import sys

            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from code_diff_generator import CodeDiffGenerator

            generator = CodeDiffGenerator()
            diff_result = generator.generate_diff(code_changes)

            # Store diff in proposal
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET code_diff = %s,
                        code_changes = %s
                    WHERE id = %s
                """,
                    (
                        json.dumps(diff_result),
                        code_changes[0].get("after", "") if len(code_changes) > 0 else "",
                        proposal_id,
                    ),
                )
                conn.commit()
                cur.close()
            finally:
                conn.close()

            result["diff_generated"] = True
            result["files_changed"] = diff_result["summary"]["total_files"]
            result["lines_added"] = diff_result["summary"]["total_added"]
            result["lines_removed"] = diff_result["summary"]["total_removed"]
            print(
                f"✅ Code diff generated for proposal {proposal_id}: {diff_result['summary']['total_files']} files, +{diff_result['summary']['total_added']} -{diff_result['summary']['total_removed']}"
            )

        except Exception as e:
            print(f"⚠️  Diff generation failed for proposal {proposal_id}: {e}")
            result["diff_generated"] = False
            result["diff_error"] = str(e)

    return result


def generate_diff_for_proposal(proposal_id: int, code_changes: List[Dict]) -> Dict:
    """
    Generate and store code diff for an existing proposal.

    Args:
        proposal_id: ID of the proposal
        code_changes: List of file changes [{'path': str, 'before': str, 'after': str}]

    Returns:
        Dict with diff generation results

    Example:
        generate_diff_for_proposal(
            proposal_id=36,
            code_changes=[{
                'path': '/app/routes.py',
                'before': 'old code...',
                'after': 'new code...'
            }]
        )
    """
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from code_diff_generator import CodeDiffGenerator

        # Generate diff
        generator = CodeDiffGenerator()
        diff_result = generator.generate_diff(code_changes)

        # Store in database
        conn = get_db()
        try:
            cur = conn.cursor()

            # Concatenate all 'after' content for code_changes field
            all_after_code = "\n\n".join(
                [f"# File: {change.get('path', 'unknown')}\n{change.get('after', '')}" for change in code_changes]
            )

            cur.execute(
                """
                UPDATE improvement_proposals
                SET code_diff = %s,
                    code_changes = %s
                WHERE id = %s
                RETURNING id, title
            """,
                (json.dumps(diff_result), all_after_code, proposal_id),
            )

            result = cur.fetchone()
            conn.commit()
            cur.close()
        finally:
            conn.close()

        if result:
            return {
                "success": True,
                "proposal_id": result[0],
                "proposal_title": result[1],
                "diff_generated": True,
                "files_changed": diff_result["summary"]["total_files"],
                "lines_added": diff_result["summary"]["total_added"],
                "lines_removed": diff_result["summary"]["total_removed"],
                "lines_modified": diff_result["summary"]["total_modified"],
            }
        else:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_proposal_with_agents(proposal) -> Dict:
    """Dispatch proposal to Bridge agents for real analysis."""
    perspectives = {}
    category = proposal.get("category", "general") if isinstance(proposal, dict) else "general"

    # Support both dict and int (proposal_id) for backwards compatibility
    if isinstance(proposal, int):
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal,))
            proposal = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        if not proposal:
            return {"error": "Proposal not found"}
        category = proposal.get("category", "general")

    # Map categories to analysis prompts
    prompts = {
        "quality": "Analyze this code improvement proposal for quality impact. Is it worth implementing? What are the risks?",
        "efficiency": "Analyze this proposal for performance/efficiency impact. Will it improve or degrade system performance?",
        "security": "Review this proposal for security implications. Are there any vulnerabilities introduced or fixed?",
        "general": "Review this improvement proposal. Assess its value, risk, and implementation complexity.",
    }

    prompt_text = prompts.get(category, prompts["general"])
    context = (
        f"Proposal: {proposal.get('title', '')}\n"
        f"Description: {proposal.get('description', '')}\n"
        f"File: {proposal.get('file_path', '')}\n"
        f"Changes: {str(proposal.get('proposed_changes', ''))[:2000]}"
    )

    try:
        from tools.department_hq.services.department_dispatcher import dispatch_json

        result = dispatch_json(
            capability="research",
            prompt=f"{prompt_text}\n\n{context}",
            module_id="repair_bay",
            system_prompt="You are a senior software engineer reviewing a code improvement proposal. Provide a brief assessment: approve/reject/needs_revision, key concerns, and estimated effort (small/medium/large).",
        )
        response = result.get("response", "") if isinstance(result, dict) else str(result)
        perspectives[category] = response
    except Exception as e:
        perspectives[category] = f"Analysis failed: {e}"

    # Store analysis in metadata if we have a proposal id
    proposal_id = proposal.get("id") if isinstance(proposal, dict) else None
    if proposal_id:
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE improvement_proposals SET metadata = metadata || %s::jsonb WHERE id = %s",
                    (
                        json.dumps(
                            {
                                "agent_analysis": {
                                    "perspectives": perspectives,
                                    "analyzed_at": datetime.now().isoformat(),
                                }
                            }
                        ),
                        proposal_id,
                    ),
                )
                conn.commit()
                cur.close()
            finally:
                conn.close()
        except Exception:
            pass

    return {
        "proposal_id": proposal_id,
        "analyzed_at": datetime.now().isoformat(),
        "perspectives": perspectives,
    }


def get_recent_proposals(limit: int = 20, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict]:
    """
    Get recent improvement proposals

    Args:
        limit: Number of proposals to return
        status: Filter by status
        category: Filter by category

    Returns:
        List of proposals
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                ip.*,
                u.username as proposed_by_username,
                a.username as approved_by_username
            FROM improvement_proposals ip
            LEFT JOIN users u ON ip.proposed_by = u.id
            LEFT JOIN users a ON ip.approved_by = a.id
            WHERE 1=1
        """
        params = []

        if status:
            query += " AND ip.status = %s"
            params.append(status)

        if category:
            query += " AND ip.category = %s"
            params.append(category)

        query += " ORDER BY ip.proposed_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        proposals = cur.fetchall()

        cur.close()
    finally:
        conn.close()

    return [dict(p) for p in proposals]


def run_auto_improvement_detection():
    """
    Main function to run automatic improvement detection
    Creates proposals for detected opportunities

    Returns:
        Summary of detected improvements
    """
    print("🔍 Running automatic improvement detection...")

    opportunities = detect_improvement_opportunities()

    proposals_created = []

    for opp in opportunities:
        # Create proposal for high and medium priority opportunities
        if opp["priority"] in ["high", "medium"]:
            proposal = propose_improvement(
                title=f"{opp['type'].replace('_', ' ').title()}: {opp.get('tag', opp.get('tags', [''])[0] if opp.get('tags') else 'General')}",
                description=opp["description"],
                category=opp["category"],
                priority=opp["priority"],
                auto_detected=True,
                metadata=opp,
            )
            proposals_created.append(proposal)
            print(f"✅ Created proposal: {proposal['title']}")

    summary = {
        "opportunities_detected": len(opportunities),
        "proposals_created": len(proposals_created),
        "detection_timestamp": datetime.now().isoformat(),
        "breakdown": {},
    }

    # Group by type
    for opp in opportunities:
        opp_type = opp["type"]
        if opp_type not in summary["breakdown"]:
            summary["breakdown"][opp_type] = 0
        summary["breakdown"][opp_type] += 1

    return summary


# Example usage
if __name__ == "__main__":
    print("=" * 80)
    print("A.R.C.H.I.E. Self-Improvement Engine - Test Run")
    print("=" * 80)

    # Run detection
    summary = run_auto_improvement_detection()

    print("\n📊 Detection Summary:")
    print(f"   Total opportunities: {summary['opportunities_detected']}")
    print(f"   Proposals created: {summary['proposals_created']}")

    print("\n📋 Breakdown by type:")
    for opp_type, count in summary["breakdown"].items():
        print(f"   - {opp_type}: {count}")

    # Show recent proposals
    print("\n📝 Recent Proposals:")
    proposals = get_recent_proposals(limit=5)
    for p in proposals:
        print(f"   [{p['priority'].upper()}] {p['title']} - {p['status']}")
