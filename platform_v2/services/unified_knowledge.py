"""
Unified Knowledge Service
Phase 4: Integration Layer for A.R.C.H.I.E.'s Knowledge Ecosystem

Connects:
- Consciousness Module (analytics, memory insights)
- Obsidian Vault (documentation, notes)
- Conversation Memory (Claude Code sessions)
- Mistake Learning (error prevention)
- AI Bridge (context for local agents)

Author: A.R.C.H.I.E. Platform
Date: 2026-01-11
"""

import json
import logging
from datetime import datetime
from services.time_utils import now_local_str
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("archie_platform")


class UnifiedKnowledgeService:
    """
    Central service for all knowledge operations across A.R.C.H.I.E.

    Provides:
    - Unified search across all knowledge types
    - Cross-module synchronization
    - Mistake learning loop integration
    - AI agent context retrieval
    """

    # Knowledge type weights for ranking
    TYPE_WEIGHTS = {
        "mistake_learned": 1.3,  # Highest priority - prevent repetition
        "vault_note": 1.2,  # Curated documentation
        "code_snippet": 1.1,  # Proven patterns
        "improvement": 1.0,  # Historical fixes
        "conversation_memory": 0.9,  # Dynamic learning
        "github_file": 0.8,  # Indexed files
    }

    # Archie_Brain category mappings
    ARCHIE_CATEGORIES = {
        "development": {
            "keywords": [
                "code",
                "function",
                "class",
                "bug",
                "feature",
                "refactor",
                "implement",
                "api",
            ],
            "icon": "💻",
            "priority": 1,
        },
        "infrastructure": {
            "keywords": [
                "docker",
                "deploy",
                "backup",
                "database",
                "postgres",
                "compose",
                "server",
                "nginx",
            ],
            "icon": "🏗️",
            "priority": 2,
        },
        "ai_learning": {
            "keywords": [
                "model",
                "prompt",
                "training",
                "knowledge",
                "claude",
                "llm",
                "embedding",
                "ai",
            ],
            "icon": "🧠",
            "priority": 3,
        },
        "mistake_prevention": {
            "keywords": [
                "error",
                "fix",
                "issue",
                "problem",
                "exception",
                "debug",
                "traceback",
            ],
            "icon": "⚠️",
            "priority": 4,
        },
        "documentation": {
            "keywords": [
                "docs",
                "readme",
                "guide",
                "tutorial",
                "comment",
                "docstring",
                "explain",
            ],
            "icon": "📚",
            "priority": 5,
        },
    }

    def __init__(self, db_connection=None):
        """Initialize with optional database connection"""
        self._db = db_connection
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

    def _get_db(self):
        """Get database connection"""
        if self._db:
            return self._db

        import os
        from database import _get_db_password

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    # =========================================================================
    # UNIFIED SEARCH
    # =========================================================================

    def search(
        self,
        query: str,
        knowledge_types: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit: int = 10,
        include_mistakes: bool = True,
    ) -> Dict[str, Any]:
        """
        Unified search across all knowledge types.

        Args:
            query: Search query
            knowledge_types: Filter by types (vault_note, conversation_memory, etc.)
            categories: Filter by Archie_Brain categories
            limit: Maximum results
            include_mistakes: Whether to include mistake_learned entries (always prioritized)

        Returns:
            Dict with results, stats, and metadata
        """
        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Build search query
            sql = """
                SELECT
                    id,
                    knowledge_type,
                    title,
                    SUBSTRING(content, 1, 500) as content_preview,
                    category,
                    tags,
                    importance_score,
                    created_at,
                    updated_at,
                    -- Calculate weighted score
                    CASE knowledge_type
                        WHEN 'mistake_learned' THEN importance_score * 1.3
                        WHEN 'vault_note' THEN importance_score * 1.2
                        WHEN 'code_snippet' THEN importance_score * 1.1
                        WHEN 'improvement' THEN importance_score * 1.0
                        WHEN 'conversation_memory' THEN importance_score * 0.9
                        ELSE importance_score * 0.8
                    END as weighted_score
                FROM knowledge_base
                WHERE 1=1
            """
            params = []

            # Add text search
            if query:
                sql += """
                    AND (
                        title ILIKE %s
                        OR content ILIKE %s
                        OR %s = ANY(tags)
                    )
                """
                search_pattern = f"%{query}%"
                params.extend([search_pattern, search_pattern, query.lower()])

            # Filter by knowledge types
            if knowledge_types:
                sql += " AND knowledge_type = ANY(%s)"
                params.append(knowledge_types)

            # Filter by categories
            if categories:
                sql += " AND category = ANY(%s)"
                params.append(categories)

            # Order by weighted score
            sql += """
                ORDER BY
                    CASE WHEN knowledge_type = 'mistake_learned' THEN 0 ELSE 1 END,
                    weighted_score DESC,
                    updated_at DESC
                LIMIT %s
            """
            params.append(limit)

            cur.execute(sql, params)
            results = [dict(row) for row in cur.fetchall()]

            # Get total count
            count_sql = "SELECT COUNT(*) FROM knowledge_base WHERE 1=1"
            if query:
                count_sql += " AND (title ILIKE %s OR content ILIKE %s)"
                cur.execute(count_sql, [search_pattern, search_pattern])
            else:
                cur.execute(count_sql)

            total_count = cur.fetchone()["count"]

            cur.close()
            if not self._db:
                conn.close()

            return {
                "success": True,
                "results": results,
                "count": len(results),
                "total": total_count,
                "query": query,
                "filters": {
                    "knowledge_types": knowledge_types,
                    "categories": categories,
                },
            }

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Search error: {e}")
            return {"success": False, "error": str(e), "results": []}

    # =========================================================================
    # KNOWLEDGE STATISTICS
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics across all knowledge types.
        Used by Consciousness and Obsidian Vault dashboards.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            stats = {
                "by_type": {},
                "by_category": {},
                "total": 0,
                "recent_24h": 0,
                "recent_7d": 0,
                "top_tags": [],
                "learning_rate": 0,
            }

            # Count by type
            cur.execute(
                """
                SELECT knowledge_type, COUNT(*) as count
                FROM knowledge_base
                GROUP BY knowledge_type
                ORDER BY count DESC
            """
            )
            for row in cur.fetchall():
                kt = row["knowledge_type"] or "unknown"
                stats["by_type"][kt] = row["count"]
                stats["total"] += row["count"]

            # Count by category
            cur.execute(
                """
                SELECT category, COUNT(*) as count
                FROM knowledge_base
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY count DESC
            """
            )
            for row in cur.fetchall():
                stats["by_category"][row["category"]] = row["count"]

            # Recent activity
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as last_24h,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as last_7d
                FROM knowledge_base
            """
            )
            row = cur.fetchone()
            stats["recent_24h"] = row["last_24h"]
            stats["recent_7d"] = row["last_7d"]

            # Learning rate (entries per day over last 30 days)
            cur.execute(
                """
                SELECT COUNT(*)::float / 30 as rate
                FROM knowledge_base
                WHERE created_at > NOW() - INTERVAL '30 days'
            """
            )
            stats["learning_rate"] = round(cur.fetchone()["rate"], 2)

            # Top tags
            cur.execute(
                """
                SELECT tag, COUNT(*) as count
                FROM knowledge_base, UNNEST(tags) as tag
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 20
            """
            )
            stats["top_tags"] = [{"tag": row["tag"], "count": row["count"]} for row in cur.fetchall()]

            cur.close()
            if not self._db:
                conn.close()

            return stats

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Statistics error: {e}")
            return {"error": str(e)}

    # =========================================================================
    # MISTAKE LEARNING LOOP
    # =========================================================================

    def check_for_similar_mistakes(self, context: str, limit: int = 3) -> List[Dict]:
        """
        Check if there are similar mistakes in the knowledge base.
        Called by AI Bridge BEFORE executing potentially risky operations.

        Args:
            context: Description of what's about to be done
            limit: Max mistakes to return

        Returns:
            List of relevant mistake_learned entries
        """
        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Search for similar mistakes
            cur.execute(
                """
                SELECT
                    id,
                    title,
                    content,
                    tags,
                    importance_score,
                    memory_metadata,
                    created_at
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                  AND (
                      title ILIKE %s
                      OR content ILIKE %s
                  )
                ORDER BY importance_score DESC, created_at DESC
                LIMIT %s
            """,
                (f"%{context}%", f"%{context}%", limit),
            )

            mistakes = [dict(row) for row in cur.fetchall()]

            cur.close()
            if not self._db:
                conn.close()

            if mistakes:
                logger.info(f"[UnifiedKnowledge] Found {len(mistakes)} similar mistakes for context: {context[:50]}...")

            return mistakes

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Mistake check error: {e}")
            return []

    def record_mistake(
        self,
        error_type: str,
        error_message: str,
        solution: str,
        context: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> Optional[int]:
        """
        Record a new mistake to the knowledge base.
        Part of the Mistake Learning Loop.

        Args:
            error_type: Type of error (e.g., "TypeError", "ConnectionError")
            error_message: Full error message
            solution: How it was fixed
            context: Additional context (git info, session, etc.)
            tags: Optional tags

        Returns:
            Knowledge entry ID or None
        """
        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            title = f"Mistake: {error_type} - {error_message[:80]}"

            content = f"""## Error Type
{error_type}

## Error Message
{error_message}

## Solution
{solution}

## Context
- Session: {context.get('session_name', 'unknown')}
- Branch: {context.get('git_branch', 'unknown')}
- File: {context.get('file_path', 'unknown')}
- Date: {now_local_str('%Y-%m-%d %H:%M %Z')}

## Prevention
To avoid this error in the future:
{solution}
"""

            # Auto-generate tags if not provided
            if not tags:
                tags = ["mistake", "error", error_type.lower()]
                # Add category-based tags
                for category, info in self.ARCHIE_CATEGORIES.items():
                    if any(kw in error_message.lower() for kw in info["keywords"]):
                        tags.append(category)

            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    source_type,
                    source_id,
                    memory_metadata
                ) VALUES (
                    'mistake_learned',
                    %s,
                    %s,
                    'mistake_prevention',
                    %s,
                    0.95,
                    %s,
                    %s,
                    %s
                ) RETURNING id
            """,
                (
                    title,
                    content,
                    tags,
                    context.get("source_type", "auto_detection"),
                    context.get("source_id", "unknown"),
                    json.dumps(
                        {
                            "error_type": error_type,
                            "auto_recorded": True,
                            "created_at": datetime.now().isoformat(),
                            **context,
                        }
                    ),
                ),
            )

            result = cur.fetchone()
            entry_id = result["id"]

            conn.commit()
            cur.close()
            if not self._db:
                conn.close()

            logger.info(f"[UnifiedKnowledge] Recorded mistake #{entry_id}: {error_type}")

            # Trigger sync to Obsidian/Consciousness
            self._trigger_knowledge_sync(entry_id, "mistake_learned")

            return entry_id

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Record mistake error: {e}")
            return None

    # =========================================================================
    # AI AGENT CONTEXT
    # =========================================================================

    def get_agent_context(
        self, task_description: str, agent_type: str = "general", max_entries: int = 5
    ) -> Dict[str, Any]:
        """
        Get relevant context for an AI agent before it executes a task.
        LOCAL-FIRST: Provides knowledge from the database before external APIs.

        Args:
            task_description: What the agent is about to do
            agent_type: Type of agent (development, infrastructure, etc.)
            max_entries: Max knowledge entries to return

        Returns:
            Dict with relevant knowledge, mistakes to avoid, and suggestions
        """
        context = {
            "mistakes_to_avoid": [],
            "relevant_knowledge": [],
            "similar_past_tasks": [],
            "suggestions": [],
        }

        try:
            # 1. Check for similar mistakes (HIGHEST PRIORITY)
            context["mistakes_to_avoid"] = self.check_for_similar_mistakes(task_description, limit=3)

            # 2. Search for relevant knowledge
            search_result = self.search(
                query=task_description,
                knowledge_types=["vault_note", "code_snippet", "improvement"],
                limit=max_entries,
            )
            if search_result.get("success"):
                context["relevant_knowledge"] = search_result["results"]

            # 3. Find similar past tasks from conversation memory
            memory_result = self.search(query=task_description, knowledge_types=["conversation_memory"], limit=3)
            if memory_result.get("success"):
                context["similar_past_tasks"] = memory_result["results"]

            # 4. Generate suggestions based on context
            if context["mistakes_to_avoid"]:
                context["suggestions"].append(
                    {
                        "type": "warning",
                        "message": f"Found {len(context['mistakes_to_avoid'])} similar mistakes. Review before proceeding.",
                    }
                )

            if context["relevant_knowledge"]:
                context["suggestions"].append(
                    {
                        "type": "info",
                        "message": f"Found {len(context['relevant_knowledge'])} relevant knowledge entries.",
                    }
                )

            return context

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Agent context error: {e}")
            return context

    # =========================================================================
    # CROSS-MODULE SYNC
    # =========================================================================

    def _trigger_knowledge_sync(self, entry_id: int, knowledge_type: str):
        """
        Trigger synchronization across modules when knowledge is added/updated.

        This ensures:
        - Obsidian Vault sees new entries
        - Consciousness analytics are updated
        - AI Bridge cache is invalidated
        """
        try:
            # Log the sync event
            logger.info(f"[UnifiedKnowledge] Sync triggered for {knowledge_type} #{entry_id}")

            # Invalidate cache
            self._cache = {}

            # Future: Could trigger webhooks or pub/sub notifications

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Sync trigger error: {e}")

    def sync_conversation_to_knowledge(self, session_id: int, insights: Dict[str, Any]) -> Dict[str, int]:
        """
        Sync conversation session insights to knowledge base.
        Called after conversation processing.

        Args:
            session_id: Conversation session ID
            insights: Extracted insights from conversation

        Returns:
            Dict with counts of entries created
        """
        created = {"knowledge_entries": 0, "mistake_entries": 0}

        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Create entries for each type of insight
            insights.get("archie_categories", ["general"])

            # If mistakes were found and solutions learned, create mistake entries
            mistakes = insights.get("mistakes_found", [])
            solutions = insights.get("solutions_learned", [])

            for i, mistake in enumerate(mistakes[:3]):  # Max 3 per session
                solution = solutions[i] if i < len(solutions) else {"pattern": "See conversation"}

                entry_id = self.record_mistake(
                    error_type=mistake.get("pattern", "unknown"),
                    error_message=f"Detected in conversation session {session_id}",
                    solution=solution.get("pattern", "unknown"),
                    context={
                        "session_id": session_id,
                        "source_type": "conversation_session",
                        "source_id": str(session_id),
                    },
                )
                if entry_id:
                    created["mistake_entries"] += 1

            cur.close()
            if not self._db:
                conn.close()

            return created

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Conversation sync error: {e}")
            return created

    def get_recent_activity(self, hours: int = 24, limit: int = 20) -> List[Dict]:
        """
        Get recent knowledge activity for Consciousness dashboard.

        Args:
            hours: Look back period
            limit: Max entries

        Returns:
            List of recent knowledge entries with metadata
        """
        try:
            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    id,
                    knowledge_type,
                    title,
                    category,
                    tags,
                    importance_score,
                    created_at,
                    source_type
                FROM knowledge_base
                WHERE created_at > NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (hours, limit),
            )

            results = [dict(row) for row in cur.fetchall()]

            cur.close()
            if not self._db:
                conn.close()

            return results

        except Exception as e:
            logger.error(f"[UnifiedKnowledge] Recent activity error: {e}")
            return []


# Singleton instance
_service_instance = None


def get_unified_knowledge_service(db_connection=None) -> UnifiedKnowledgeService:
    """Get singleton unified knowledge service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = UnifiedKnowledgeService(db_connection)
    elif db_connection is not None:
        _service_instance._db = db_connection
    return _service_instance


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: unified_knowledge.py <command> [args]")
        print("")
        print("Commands:")
        print("  stats              Get knowledge statistics")
        print("  search <query>     Search all knowledge")
        print("  check <context>    Check for similar mistakes")
        print("  recent [hours]     Get recent activity")
        sys.exit(1)

    command = sys.argv[1]
    service = UnifiedKnowledgeService()

    if command == "stats":
        stats = service.get_statistics()
        print(json.dumps(stats, indent=2, default=str))

    elif command == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        result = service.search(query)
        print(json.dumps(result, indent=2, default=str))

    elif command == "check" and len(sys.argv) > 2:
        context = " ".join(sys.argv[2:])
        mistakes = service.check_for_similar_mistakes(context)
        print(json.dumps(mistakes, indent=2, default=str))

    elif command == "recent":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        activity = service.get_recent_activity(hours)
        print(json.dumps(activity, indent=2, default=str))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
