"""
Improvement Workflow with Knowledge Integration (Phase 5)

This module integrates the unified knowledge system with the improvement workflow,
ensuring proposals include relevant context from vault_note, code_snippet, and
mistake_learned entries.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-09
Phase: 5 - Improvements Integration
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
from tools.consciousness.services.unified_knowledge_search import unified_knowledge_search
from tools.consciousness.services.mistake_detector import get_mistake_detector

logger = logging.getLogger("archie_platform")


class ImprovementWorkflow:
    """
    Orchestrates improvement proposals with knowledge context injection.

    Features:
    - Retrieves relevant knowledge when creating proposals
    - Enriches proposals with curated docs and code snippets
    - Provides context to contractors/agents
    - Tracks execution and learns from failures
    """

    def __init__(self, db_connection=None):
        """Initialize with optional database connection"""
        self.db = db_connection
        self.mistake_detector = get_mistake_detector()

    def create_proposal_with_context(
        self,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        proposed_by: int = None,
        user_id: int = None,
    ) -> Dict[str, Any]:
        """
        Create improvement proposal with relevant knowledge context.

        Args:
            title: Proposal title
            description: Detailed description
            category: Category (quality, efficiency, knowledge, etc.)
            priority: Priority level (low, medium, high)
            proposed_by: User ID of proposer
            user_id: Current user ID

        Returns:
            Dict with proposal_id, knowledge_context, and creation status
        """
        try:
            logger.info(f"[Improvement Workflow] Creating proposal with knowledge context: {title}")

            # STEP 1: Search unified knowledge base for relevant context
            knowledge_context = self._retrieve_relevant_knowledge(query=f"{title} {description}", category=category)

            # STEP 2: Check for known mistakes related to this improvement
            mistake_warnings = self._check_for_related_mistakes(description)

            # STEP 3: Find similar past improvements
            similar_improvements = self._find_similar_improvements(title, description)

            # STEP 4: Compile context metadata
            context_metadata = {
                "knowledge_entries": [k["id"] for k in knowledge_context],
                "mistake_warnings": mistake_warnings,
                "similar_improvements": [s["id"] for s in similar_improvements],
                "context_retrieved_at": datetime.now().isoformat(),
                "knowledge_quality_score": self._calculate_context_quality(knowledge_context),
            }

            # STEP 5: Create enriched proposal description
            enriched_description = self._enrich_description(
                description=description,
                knowledge_context=knowledge_context,
                mistake_warnings=mistake_warnings,
                similar_improvements=similar_improvements,
            )

            # STEP 6: Insert proposal into database
            if self.db:
                from psycopg2.extras import RealDictCursor

                cur = self.db.cursor(cursor_factory=RealDictCursor)

                cur.execute(
                    """
                    INSERT INTO improvement_proposals (
                        title,
                        description,
                        category,
                        priority,
                        status,
                        proposed_by,
                        proposed_at,
                        metadata
                    ) VALUES (
                        %s, %s, %s, %s, 'proposed', %s, NOW(), %s
                    ) RETURNING id
                """,
                    (
                        title,
                        enriched_description,
                        category,
                        priority,
                        proposed_by or user_id,
                        json.dumps(context_metadata),
                    ),
                )

                result = cur.fetchone()
                proposal_id = result["id"]

                self.db.commit()
                cur.close()

                logger.info(
                    f"[Improvement Workflow] Created proposal #{proposal_id} with {len(knowledge_context)} knowledge entries"
                )

                return {
                    "success": True,
                    "proposal_id": proposal_id,
                    "knowledge_context": knowledge_context,
                    "mistake_warnings": mistake_warnings,
                    "similar_improvements": similar_improvements,
                    "context_quality_score": context_metadata["knowledge_quality_score"],
                }
            else:
                logger.warning("[Improvement Workflow] No database connection - returning context only")
                return {
                    "success": False,
                    "error": "No database connection",
                    "knowledge_context": knowledge_context,
                    "mistake_warnings": mistake_warnings,
                }

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error creating proposal: {e}")
            return {"success": False, "error": str(e)}

    def _retrieve_relevant_knowledge(self, query: str, category: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve relevant knowledge from unified knowledge base.

        Prioritizes:
        1. mistake_learned (prevent repeating errors)
        2. vault_note (curated documentation)
        3. code_snippet (proven patterns)
        4. improvement (past successful changes)

        Args:
            query: Search query
            category: Improvement category
            limit: Max results

        Returns:
            List of knowledge entries with metadata
        """
        try:
            # Search with type priority weighting
            result = unified_knowledge_search(
                query=query,
                types=["mistake_learned", "vault_note", "code_snippet", "improvement"],
                category=category if category != "all" else None,
                limit=limit,
                offset=0,
            )

            if result and "results" in result:
                logger.info(f"[Improvement Workflow] Found {len(result['results'])} relevant knowledge entries")
                return result["results"]
            else:
                logger.warning("[Improvement Workflow] Knowledge search returned no results")
                return []

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error retrieving knowledge: {e}")
            return []

    def _check_for_related_mistakes(self, description: str) -> List[Dict[str, Any]]:
        """
        Check if improvement relates to known mistakes.

        Args:
            description: Improvement description

        Returns:
            List of related mistake entries with warnings
        """
        try:
            # Check if any known mistake patterns match
            mistake_solution = self.mistake_detector.get_solution_for_error(description)

            if mistake_solution:
                logger.warning(f"[Improvement Workflow] Found related mistake: {mistake_solution}")
                return [
                    {
                        "type": "known_mistake",
                        "solution": mistake_solution,
                        "severity": "high",
                    }
                ]

            # Get all mistakes for manual checking
            all_mistakes = self.mistake_detector.get_all_mistakes(limit=20)

            related = []
            for mistake in all_mistakes:
                # Simple keyword matching (could be enhanced with embeddings)
                mistake_content = mistake.get("content", "").lower()
                desc_lower = description.lower()

                # Check for keyword overlap
                common_keywords = set(mistake_content.split()) & set(desc_lower.split())
                if len(common_keywords) >= 3:  # At least 3 common words
                    related.append(
                        {
                            "type": "potential_mistake",
                            "mistake_id": mistake.get("id"),
                            "title": mistake.get("title"),
                            "content": mistake.get("content")[:200] + "...",
                            "severity": "medium",
                        }
                    )

            if related:
                logger.info(f"[Improvement Workflow] Found {len(related)} potentially related mistakes")

            return related

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error checking mistakes: {e}")
            return []

    def _find_similar_improvements(self, title: str, description: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Find similar past improvements.

        Args:
            title: Proposal title
            description: Proposal description
            limit: Max results

        Returns:
            List of similar improvement proposals
        """
        try:
            if not self.db:
                return []

            from psycopg2.extras import RealDictCursor

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            # Search for similar proposals by keywords
            search_terms = f"%{title.lower()}%"

            cur.execute(
                """
                SELECT
                    id,
                    title,
                    description,
                    category,
                    status,
                    implemented_at,
                    metadata
                FROM improvement_proposals
                WHERE
                    (LOWER(title) LIKE %s OR LOWER(description) LIKE %s)
                    AND status IN ('deployed', 'executed', 'approved')
                ORDER BY implemented_at DESC NULLS LAST
                LIMIT %s
            """,
                (search_terms, search_terms, limit),
            )

            results = cur.fetchall()
            cur.close()

            if results:
                logger.info(f"[Improvement Workflow] Found {len(results)} similar past improvements")

            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error finding similar improvements: {e}")
            return []

    def _calculate_context_quality(self, knowledge_context: List[Dict]) -> float:
        """
        Calculate quality score for retrieved knowledge context.

        Scoring:
        - High importance entries: +0.3
        - Vault notes: +0.2
        - Mistake warnings: +0.3
        - Code snippets: +0.15
        - Recency: +0.05

        Args:
            knowledge_context: List of knowledge entries

        Returns:
            Quality score (0.0-1.0)
        """
        if not knowledge_context:
            return 0.0

        score = 0.0
        max_score = 0.0

        for entry in knowledge_context:
            entry_score = 0.0

            # Importance weighting
            importance = entry.get("importance_score", 0.5)
            if importance >= 0.8:
                entry_score += 0.3
            elif importance >= 0.6:
                entry_score += 0.2

            # Type weighting
            knowledge_type = entry.get("knowledge_type", "")
            if knowledge_type == "vault_note":
                entry_score += 0.2
            elif knowledge_type == "mistake_learned":
                entry_score += 0.3
            elif knowledge_type == "code_snippet":
                entry_score += 0.15

            # Recency bonus
            created_at = entry.get("created_at")
            if created_at:
                try:
                    from datetime import datetime, timedelta

                    created_date = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                    if datetime.now().astimezone() - created_date < timedelta(days=30):
                        entry_score += 0.05
                except Exception:
                    pass

            score += entry_score
            max_score += 1.0  # Max possible per entry

        # Normalize to 0.0-1.0
        return min(score / max(max_score, 1.0), 1.0)

    def _enrich_description(
        self,
        description: str,
        knowledge_context: List[Dict],
        mistake_warnings: List[Dict],
        similar_improvements: List[Dict],
    ) -> str:
        """
        Enrich proposal description with knowledge context.

        Args:
            description: Original description
            knowledge_context: Retrieved knowledge entries
            mistake_warnings: Related mistake warnings
            similar_improvements: Similar past improvements

        Returns:
            Enriched description with context sections
        """
        enriched = description + "\n\n---\n\n"

        # Add mistake warnings
        if mistake_warnings:
            enriched += "## ⚠️ Related Mistakes to Avoid\n\n"
            for warning in mistake_warnings:
                enriched += f"- **{warning.get('type', 'Warning')}**: {warning.get('solution', warning.get('title', 'Check related mistake'))}\n"
            enriched += "\n"

        # Add relevant knowledge
        if knowledge_context:
            enriched += "## 📚 Relevant Knowledge\n\n"
            for entry in knowledge_context[:5]:  # Top 5
                knowledge_type = entry.get("knowledge_type", "knowledge").replace("_", " ").title()
                title = entry.get("title", "Untitled")
                content = entry.get("content", "")[:150] + "..."
                enriched += f"- **[{knowledge_type}]** {title}\n  {content}\n\n"

        # Add similar improvements
        if similar_improvements:
            enriched += "## 🔧 Similar Past Improvements\n\n"
            for improvement in similar_improvements[:3]:  # Top 3
                title = improvement.get("title", "Untitled")
                status = improvement.get("status", "unknown")
                enriched += f"- {title} (Status: {status})\n"
            enriched += "\n"

        enriched += "---\n\n*Knowledge context auto-generated by A.R.C.H.I.E. Brain (Phase 5)*"

        return enriched

    def track_execution(
        self,
        proposal_id: int,
        agent_id: Optional[int] = None,
        action: str = "execute",
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Track improvement execution and learn from failures.

        Args:
            proposal_id: Improvement proposal ID
            agent_id: Agent executing the improvement
            action: Action type (execute, test, deploy, rollback)
            success: Whether execution succeeded
            error_message: Error message if failed
            metadata: Additional execution metadata

        Returns:
            Tracking result with learning status
        """
        try:
            logger.info(
                f"[Improvement Workflow] Tracking execution for proposal #{proposal_id}: {action} (success={success})"
            )

            # STEP 1: Log execution
            execution_log = {
                "proposal_id": proposal_id,
                "agent_id": agent_id,
                "action": action,
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "error_message": error_message,
                "metadata": metadata or {},
            }

            # STEP 2: If failed, create mistake_learned entry
            mistake_entry = None
            if not success and error_message:
                mistake_entry = self._learn_from_failure(
                    proposal_id=proposal_id,
                    error_message=error_message,
                    action=action,
                    metadata=metadata,
                )

            # STEP 3: Update proposal status
            if self.db:
                from psycopg2.extras import RealDictCursor

                cur = self.db.cursor(cursor_factory=RealDictCursor)

                # Update proposal metadata with execution log
                cur.execute(
                    """
                    UPDATE improvement_proposals
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                    WHERE id = %s
                """,
                    (json.dumps({"last_execution": execution_log}), proposal_id),
                )

                # If failed, update status
                if not success:
                    cur.execute(
                        """
                        UPDATE improvement_proposals
                        SET status = 'failed'
                        WHERE id = %s
                    """,
                        (proposal_id,),
                    )

                self.db.commit()
                cur.close()

            return {
                "success": True,
                "execution_logged": True,
                "mistake_learned": mistake_entry is not None,
                "mistake_entry_id": mistake_entry.get("id") if mistake_entry else None,
            }

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error tracking execution: {e}")
            return {"success": False, "error": str(e)}

    def _learn_from_failure(
        self,
        proposal_id: int,
        error_message: str,
        action: str,
        metadata: Optional[Dict],
    ) -> Optional[Dict[str, Any]]:
        """
        Create mistake_learned entry from failed improvement.

        Args:
            proposal_id: Failed proposal ID
            error_message: Error message
            action: Action that failed
            metadata: Additional context

        Returns:
            Created mistake entry or None
        """
        try:
            logger.info(f"[Improvement Workflow] Learning from failure: proposal #{proposal_id}")

            # Use mistake detector to analyze and store
            context = {
                "source": "improvement_workflow",
                "proposal_id": proposal_id,
                "action": action,
                "metadata": metadata or {},
            }

            # Detect and learn
            mistake = self.mistake_detector.detect_and_learn(error_message=error_message, context=context)

            if mistake:
                logger.info(f"[Improvement Workflow] Created mistake_learned entry: {mistake.get('title')}")
                return mistake
            else:
                logger.warning(f"[Improvement Workflow] No mistake pattern matched for error: {error_message[:100]}")
                return None

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error learning from failure: {e}")
            return None

    def get_proposal_context(self, proposal_id: int) -> Dict[str, Any]:
        """
        Get full knowledge context for a proposal.

        Useful for contractors/agents who need all relevant information.

        Args:
            proposal_id: Proposal ID

        Returns:
            Dict with proposal details and knowledge context
        """
        try:
            if not self.db:
                return {"success": False, "error": "No database connection"}

            from psycopg2.extras import RealDictCursor

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            # Get proposal
            cur.execute(
                """
                SELECT * FROM improvement_proposals WHERE id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()

            if not proposal:
                cur.close()
                return {"success": False, "error": "Proposal not found"}

            proposal = dict(proposal)

            # Extract knowledge IDs from metadata
            metadata = proposal.get("metadata", {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            knowledge_ids = metadata.get("knowledge_entries", [])

            # Fetch knowledge entries
            knowledge_context = []
            if knowledge_ids:
                cur.execute(
                    """
                    SELECT * FROM knowledge_base
                    WHERE id = ANY(%s)
                    ORDER BY importance_score DESC
                """,
                    (knowledge_ids,),
                )

                knowledge_context = [dict(r) for r in cur.fetchall()]

            cur.close()

            return {
                "success": True,
                "proposal": proposal,
                "knowledge_context": knowledge_context,
                "mistake_warnings": metadata.get("mistake_warnings", []),
                "similar_improvements": metadata.get("similar_improvements", []),
                "context_quality_score": metadata.get("knowledge_quality_score", 0.0),
            }

        except Exception as e:
            logger.error(f"[Improvement Workflow] Error getting proposal context: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_workflow_instance = None


def get_improvement_workflow(db_connection=None):
    """Get singleton improvement workflow instance"""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = ImprovementWorkflow(db_connection)
    elif db_connection is not None:
        _workflow_instance.db = db_connection
    return _workflow_instance
