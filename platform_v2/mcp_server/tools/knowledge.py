"""
A.R.C.H.I.E. MCP Server - Knowledge & Memory Tools
Phase 50.2: AI Integration Hub

Tools for searching knowledge, storing memories, recalling context,
and managing user preferences via Model Context Protocol.
"""

import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Any, Optional

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.knowledge")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", "archie_secure_2024"),
}


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


# ============================================================================
# SEARCH KNOWLEDGE TOOL
# ============================================================================


async def search_knowledge_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search A.R.C.H.I.E.'s unified knowledge base

    Searches across all knowledge types with intelligent ranking:
    - mistake_learned (1.3x) - Prevent repeating errors
    - vault_note (1.2x) - Curated documentation
    - code_snippet (1.1x) - Proven patterns
    - improvement (1.0x) - Historical changes
    - github_file (0.8x) - Indexed files
    - conversation_memory (0.8x) - Dynamic learning
    """
    query = arguments.get("query", "")
    types = arguments.get("types")  # Optional: filter by knowledge types
    category = arguments.get("category")  # Optional: filter by category
    limit = min(arguments.get("limit", 10), 50)  # Cap at 50

    if not query:
        return {"success": False, "error": "Query is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Type weights for ranking
        type_weights = {
            "mistake_learned": 1.3,
            "vault_note": 1.2,
            "code_snippet": 1.1,
            "improvement": 1.0,
            "github_file": 0.8,
            "conversation_memory": 0.8,
        }

        # Build query conditions
        conditions = ["(title ILIKE %s OR content ILIKE %s)"]
        params = [f"%{query}%", f"%{query}%"]

        if types:
            if isinstance(types, str):
                types = [types]
            placeholders = ",".join(["%s"] * len(types))
            conditions.append(f"knowledge_type IN ({placeholders})")
            params.extend(types)

        if category:
            conditions.append("category = %s")
            params.append(category)

        where_clause = " AND ".join(conditions)

        # Execute search with weighted ranking
        cur.execute(
            f"""
            SELECT
                id,
                knowledge_type,
                title,
                LEFT(content, 500) as content_preview,
                category,
                tags,
                importance_score,
                access_count,
                created_at,
                CASE
                    WHEN knowledge_type = 'mistake_learned' THEN importance_score * 1.3
                    WHEN knowledge_type = 'vault_note' THEN importance_score * 1.2
                    WHEN knowledge_type = 'code_snippet' THEN importance_score * 1.1
                    WHEN knowledge_type = 'improvement' THEN importance_score * 1.0
                    ELSE importance_score * 0.8
                END as weighted_score
            FROM knowledge_base
            WHERE {where_clause}
            ORDER BY weighted_score DESC, access_count DESC
            LIMIT %s
        """,
            params + [limit],
        )

        results = [dict(row) for row in cur.fetchall()]

        # Update access counts for returned results
        if results:
            ids = [r["id"] for r in results]
            cur.execute(
                """
                UPDATE knowledge_base
                SET access_count = access_count + 1, last_accessed = NOW()
                WHERE id = ANY(%s)
            """,
                (ids,),
            )
            conn.commit()

        cur.close()
        conn.close()

        # Format results for AI consumption
        formatted_results = []
        for r in results:
            formatted_results.append(
                {
                    "id": r["id"],
                    "type": r["knowledge_type"],
                    "title": r["title"],
                    "content": r["content_preview"],
                    "category": r["category"],
                    "tags": r["tags"] or [],
                    "relevance_score": (float(r["weighted_score"]) if r["weighted_score"] else 0.0),
                }
            )

        return {
            "success": True,
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results,
            "search_types": types or ["all"],
            "tip": "Use type filters for more specific results: mistake_learned, vault_note, code_snippet, github_file, conversation_memory",
        }

    except Exception as e:
        logger.error(f"Error in search_knowledge: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# STORE MEMORY TOOL
# ============================================================================


async def store_memory_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store information in A.R.C.H.I.E.'s long-term memory

    Creates a new entry in the knowledge base that persists across sessions.
    Use this for important facts, preferences, procedures, or learnings.
    """
    title = arguments.get("title", "")
    content = arguments.get("content", "")
    memory_type = arguments.get("memory_type", "conversation_memory")
    category = arguments.get("category", "general")
    tags = arguments.get("tags", [])
    importance = min(max(arguments.get("importance", 0.6), 0.0), 1.0)

    if not content:
        return {"success": False, "error": "Content is required"}

    # Validate memory type
    valid_types = [
        "conversation_memory",
        "vault_note",
        "code_snippet",
        "improvement",
        "mistake_learned",
        "github_file",
    ]
    if memory_type not in valid_types:
        return {
            "success": False,
            "error": f"Invalid memory_type. Must be one of: {valid_types}",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Auto-generate title if not provided
        if not title:
            title = content[:100] + ("..." if len(content) > 100 else "")

        # Ensure tags is a list
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        # Store in knowledge_base
        cur.execute(
            """
            INSERT INTO knowledge_base
            (knowledge_type, title, content, category, tags, importance_score, source_type)
            VALUES (%s, %s, %s, %s, %s, %s, 'mcp_tool')
            RETURNING id, created_at
        """,
            (memory_type, title, content, category, tags, importance),
        )

        result = cur.fetchone()
        memory_id = result["id"]
        created_at = result["created_at"]

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Stored memory ID {memory_id}: {title[:50]}...")

        return {
            "success": True,
            "memory_id": memory_id,
            "title": title,
            "type": memory_type,
            "category": category,
            "importance": importance,
            "created_at": created_at.isoformat() if created_at else None,
            "message": f"Memory stored successfully with ID {memory_id}",
        }

    except Exception as e:
        logger.error(f"Error in store_memory: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# GET USER PREFERENCES TOOL
# ============================================================================


async def get_preferences_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve learned user preferences from A.R.C.H.I.E.'s memory

    Returns preferences organized by category with confidence scores.
    Higher confidence means more consistently observed behavior.
    """
    user_id = arguments.get("user_id", 2)  # Default to admin user (ID 2)
    category = arguments.get("category")  # Optional filter
    min_confidence = arguments.get("min_confidence", 0.5)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Use the database function for preference retrieval
        cur.execute(
            "SELECT * FROM get_user_preferences(%s, %s, %s)",
            (user_id, category, min_confidence),
        )

        prefs = [dict(p) for p in cur.fetchall()]

        # Also check knowledge_base for preference-type memories
        cur.execute(
            """
            SELECT title, content, category, importance_score, tags
            FROM knowledge_base
            WHERE knowledge_type = 'conversation_memory'
            AND (category ILIKE '%preference%' OR 'preference' = ANY(tags))
            ORDER BY importance_score DESC
            LIMIT 20
        """
        )

        memory_prefs = [dict(p) for p in cur.fetchall()]

        cur.close()
        conn.close()

        # Organize preferences by category
        by_category = {}
        for pref in prefs:
            cat = pref.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(
                {
                    "key": pref.get("preference_key"),
                    "value": pref.get("preference_value"),
                    "confidence": float(pref.get("confidence", 0)),
                    "times_confirmed": pref.get("times_confirmed", 1),
                }
            )

        return {
            "success": True,
            "user_id": user_id,
            "total_preferences": len(prefs),
            "preferences_by_category": by_category,
            "preference_memories": memory_prefs[:5],
            "filters_applied": {"category": category, "min_confidence": min_confidence},
        }

    except Exception as e:
        logger.error(f"Error in get_preferences: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# RECALL CONTEXT TOOL
# ============================================================================


async def recall_context_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recall relevant context from past conversations and memories

    Uses semantic matching to find the most relevant historical context
    for a given topic or query. Great for maintaining continuity across sessions.
    """
    topic = arguments.get("topic", "")
    context_type = arguments.get("context_type")  # Optional: conversation, fact, procedure
    limit = min(arguments.get("limit", 5), 20)
    include_recent = arguments.get("include_recent", True)

    if not topic:
        return {"success": False, "error": "Topic is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        results = {
            "relevant_memories": [],
            "recent_context": [],
            "related_mistakes": [],
            "related_procedures": [],
        }

        # Search for relevant memories
        memory_conditions = ["content ILIKE %s"]
        memory_params = [f"%{topic}%"]

        if context_type:
            type_mapping = {
                "conversation": "conversation_memory",
                "fact": "vault_note",
                "procedure": "code_snippet",
            }
            if context_type in type_mapping:
                memory_conditions.append("knowledge_type = %s")
                memory_params.append(type_mapping[context_type])

        cur.execute(
            f"""
            SELECT id, knowledge_type, title, LEFT(content, 300) as content,
                   category, tags, importance_score, created_at
            FROM knowledge_base
            WHERE {" AND ".join(memory_conditions)}
            ORDER BY importance_score DESC, created_at DESC
            LIMIT %s
        """,
            memory_params + [limit],
        )

        results["relevant_memories"] = [dict(r) for r in cur.fetchall()]

        # Get recent conversation context if requested
        if include_recent:
            cur.execute(
                """
                SELECT id, title, LEFT(content, 200) as content, created_at
                FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                ORDER BY created_at DESC
                LIMIT 5
            """
            )
            results["recent_context"] = [dict(r) for r in cur.fetchall()]

        # Check for related mistakes
        cur.execute(
            """
            SELECT id, title, LEFT(content, 200) as content, importance_score
            FROM knowledge_base
            WHERE knowledge_type = 'mistake_learned'
            AND (title ILIKE %s OR content ILIKE %s)
            ORDER BY importance_score DESC
            LIMIT 3
        """,
            (f"%{topic}%", f"%{topic}%"),
        )

        results["related_mistakes"] = [dict(r) for r in cur.fetchall()]

        # Check for related procedures/code snippets
        cur.execute(
            """
            SELECT id, title, LEFT(content, 200) as content, category
            FROM knowledge_base
            WHERE knowledge_type IN ('code_snippet', 'vault_note')
            AND (title ILIKE %s OR content ILIKE %s)
            ORDER BY importance_score DESC
            LIMIT 3
        """,
            (f"%{topic}%", f"%{topic}%"),
        )

        results["related_procedures"] = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        total_context = (
            len(results["relevant_memories"])
            + len(results["recent_context"])
            + len(results["related_mistakes"])
            + len(results["related_procedures"])
        )

        return {
            "success": True,
            "topic": topic,
            "total_context_items": total_context,
            "context": results,
            "tip": "Check related_mistakes to avoid repeating past errors!",
        }

    except Exception as e:
        logger.error(f"Error in recall_context: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# LEARN PREFERENCE TOOL
# ============================================================================


async def learn_preference_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Teach A.R.C.H.I.E. a new user preference

    Stores a preference that will influence future interactions.
    Preferences are reinforced when confirmed multiple times.
    """
    user_id = arguments.get("user_id", 2)  # Default to admin user (ID 2)
    category = arguments.get("category", "general")
    key = arguments.get("key", "")
    value = arguments.get("value", "")
    confidence = min(max(arguments.get("confidence", 0.6), 0.0), 1.0)
    context = arguments.get("context")

    if not key or not value:
        return {"success": False, "error": "Both key and value are required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Use the database function for preference learning
        cur.execute(
            "SELECT learn_preference(%s, %s, %s, %s, %s, %s)",
            (
                user_id,
                category,
                key,
                value,
                confidence,
                json.dumps(context) if context else None,
            ),
        )

        result = cur.fetchone()
        # Handle both dict (RealDictCursor) and tuple results
        pref_id = result["learn_preference"] if isinstance(result, dict) else result[0]
        conn.commit()

        cur.close()
        conn.close()

        logger.info(f"Learned preference {category}/{key} = {value}")

        return {
            "success": True,
            "preference_id": pref_id,
            "category": category,
            "key": key,
            "value": value,
            "confidence": confidence,
            "message": f"Preference learned: {category}/{key} = {value}",
        }

    except Exception as e:
        logger.error(f"Error in learn_preference: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# GET KNOWLEDGE STATS TOOL
# ============================================================================


async def get_knowledge_stats_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get statistics about A.R.C.H.I.E.'s knowledge base

    Returns counts by type, category distribution, and growth trends.
    """
    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        stats = {}

        # Count by type
        cur.execute(
            """
            SELECT knowledge_type, COUNT(*) as count
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY count DESC
        """
        )
        stats["by_type"] = {row["knowledge_type"]: row["count"] for row in cur.fetchall()}

        # Count by category
        cur.execute(
            """
            SELECT category, COUNT(*) as count
            FROM knowledge_base
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """
        )
        stats["top_categories"] = {row["category"]: row["count"] for row in cur.fetchall()}

        # Total count
        cur.execute("SELECT COUNT(*) as total FROM knowledge_base")
        stats["total_entries"] = cur.fetchone()["total"]

        # Active count (excluding archived archie_v1 legacy entries)
        cur.execute("SELECT COUNT(*) as total FROM knowledge_base WHERE source_type != 'archie_v1'")
        stats["active_entries"] = cur.fetchone()["total"]

        # Recent additions
        cur.execute(
            """
            SELECT COUNT(*) as count
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '7 days'
        """
        )
        stats["added_last_week"] = cur.fetchone()["count"]

        # Most accessed
        cur.execute(
            """
            SELECT id, title, knowledge_type, access_count
            FROM knowledge_base
            ORDER BY access_count DESC
            LIMIT 5
        """
        )
        stats["most_accessed"] = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "success": True,
            "stats": stats,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error in get_knowledge_stats: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# GITHUB REPOSITORY TOOLS
# ============================================================================


async def github_list_repos_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List all tracked GitHub repositories with file counts."""
    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}
    try:
        cur.execute(
            """
            SELECT gr.id, gr.repo_name, gr.repo_type, gr.status, gr.indexed_files, gr.indexed_at,
                   (SELECT COUNT(*) FROM knowledge_base kb
                    WHERE kb.knowledge_type = 'github_file' AND kb.repo_type = gr.repo_type) as actual_file_count
            FROM github_repositories gr ORDER BY gr.repo_name
        """
        )
        repos = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN is_code THEN 1 ELSE 0 END) as code,
                   SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END) as docs,
                   SUM(CASE WHEN is_configuration THEN 1 ELSE 0 END) as config
            FROM knowledge_base WHERE knowledge_type = 'github_file' OR source_type = 'github_selective'
        """
        )
        stats = dict(cur.fetchone())
        for r in repos:
            if r.get("indexed_at"):
                r["indexed_at"] = r["indexed_at"].isoformat()
        return {
            "success": True,
            "repositories": repos,
            "stats": stats,
            "count": len(repos),
        }
    except Exception as e:
        logger.error(f"Error in github_list_repos: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


async def github_index_repo_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Index a GitHub repository into the knowledge base."""
    import requests as http_requests

    repo_url = arguments.get("repo_url", "").strip()
    priority = arguments.get("priority", "high")
    max_files = arguments.get("max_files")
    if not repo_url:
        return {"success": False, "error": "repo_url is required"}

    # Call the platform endpoint internally
    platform_url = f"http://{os.getenv('PLATFORM_HOST', 'localhost')}:{os.getenv('PLATFORM_PORT', '3000')}/tools/consciousness/github/index-selective"
    try:
        body = {"repo_url": repo_url, "priority": priority}
        if max_files is not None:
            body["max_files"] = int(max_files)
        # Use internal API key auth
        resp = http_requests.post(
            platform_url,
            json=body,
            headers={"Content-Type": "application/json"},
            cookies={"session": "mcp-internal"},
            timeout=300,
        )
        if resp.status_code == 200:
            return resp.json()
        # Fallback: index directly via DB if platform not reachable
        return {
            "success": False,
            "error": f"Platform returned HTTP {resp.status_code}. Use the web UI to index repos.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Could not reach platform: {str(e)}. Use the web UI to index repos.",
        }


async def github_search_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Semantic search across indexed GitHub files."""
    query = arguments.get("query", "").strip()
    limit = min(arguments.get("limit", 10), 50)
    if not query:
        return {"success": False, "error": "query is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}
    try:
        # Try semantic search via embeddings
        try:
            from tools.consciousness.memory_service import semantic_search

            results = semantic_search(
                query,
                table="knowledge_base",
                limit=limit,
                filter_sql="AND (source_type = 'github_selective' OR knowledge_type = 'github_file')",
            )
            if results:
                return {
                    "success": True,
                    "results": [
                        {
                            "title": r.get("title", ""),
                            "file_path": r.get("file_path", ""),
                            "similarity": r.get("similarity"),
                            "snippet": (r.get("content", "") or "")[:500],
                            "repo_type": r.get("repo_type", ""),
                            "is_code": r.get("is_code", False),
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
        except Exception:
            pass  # Fall back to text search

        # Text search fallback
        cur.execute(
            """
            SELECT id, title, file_path, repo_type, is_code, is_documentation,
                   LEFT(content, 500) as snippet
            FROM knowledge_base
            WHERE (source_type = 'github_selective' OR knowledge_type = 'github_file')
              AND (title ILIKE %s OR content ILIKE %s)
            ORDER BY importance_score DESC
            LIMIT %s
        """,
            (f"%{query}%", f"%{query}%", limit),
        )
        results = [dict(r) for r in cur.fetchall()]
        return {
            "success": True,
            "results": results,
            "count": len(results),
            "search_type": "text",
        }
    except Exception as e:
        logger.error(f"Error in github_search: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_knowledge_tools():
    """Register all knowledge tools with the MCP server"""

    # Search Knowledge
    register_tool(
        name="search_knowledge",
        category="knowledge",
        description="Search A.R.C.H.I.E.'s unified knowledge base across all types (mistakes, docs, code, conversations). Returns ranked results with relevance scores.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - will match against titles and content",
                },
                "types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by knowledge types: mistake_learned, vault_note, code_snippet, github_file, conversation_memory",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g., database, api, frontend)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10, max: 50)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=search_knowledge_handler,
        requires_permission="read",
    )

    # Store Memory
    register_tool(
        name="store_memory",
        category="knowledge",
        description="Store new information in A.R.C.H.I.E.'s long-term memory. Use for important facts, learnings, procedures, or preferences that should persist.",
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to store (required)",
                },
                "title": {
                    "type": "string",
                    "description": "Brief title (auto-generated if not provided)",
                },
                "memory_type": {
                    "type": "string",
                    "enum": [
                        "conversation_memory",
                        "vault_note",
                        "code_snippet",
                        "improvement",
                        "mistake_learned",
                    ],
                    "description": "Type of memory (default: conversation_memory)",
                    "default": "conversation_memory",
                },
                "category": {
                    "type": "string",
                    "description": "Category for organization (e.g., database, api, preferences)",
                    "default": "general",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for easier retrieval",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance score 0.0-1.0 (default: 0.6)",
                    "default": 0.6,
                },
            },
            "required": ["content"],
        },
        handler=store_memory_handler,
        requires_permission="write",
    )

    # Get User Preferences
    register_tool(
        name="get_user_preferences",
        category="knowledge",
        description="Retrieve learned user preferences from memory. Returns preferences organized by category with confidence scores.",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default: 2 for admin)",
                    "default": 2,
                },
                "category": {
                    "type": "string",
                    "description": "Filter by preference category",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold (default: 0.5)",
                    "default": 0.5,
                },
            },
        },
        handler=get_preferences_handler,
        requires_permission="read",
    )

    # Recall Context
    register_tool(
        name="recall_context",
        category="knowledge",
        description="Recall relevant historical context for a topic. Returns memories, recent conversations, related mistakes to avoid, and procedures.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to recall context for (required)",
                },
                "context_type": {
                    "type": "string",
                    "enum": ["conversation", "fact", "procedure"],
                    "description": "Filter by context type",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per category (default: 5, max: 20)",
                    "default": 5,
                },
                "include_recent": {
                    "type": "boolean",
                    "description": "Include recent conversation context",
                    "default": True,
                },
            },
            "required": ["topic"],
        },
        handler=recall_context_handler,
        requires_permission="read",
    )

    # Learn Preference
    register_tool(
        name="learn_preference",
        category="knowledge",
        description="Teach A.R.C.H.I.E. a new user preference. Preferences influence future interactions and are reinforced when confirmed.",
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Preference category (e.g., coding_style, communication, schedule)",
                    "default": "general",
                },
                "key": {
                    "type": "string",
                    "description": "Preference key/name (required)",
                },
                "value": {
                    "type": "string",
                    "description": "Preference value (required)",
                },
                "user_id": {
                    "type": "integer",
                    "description": "User ID (default: 1)",
                    "default": 1,
                },
                "confidence": {
                    "type": "number",
                    "description": "Initial confidence 0.0-1.0 (default: 0.6)",
                    "default": 0.6,
                },
                "context": {
                    "type": "object",
                    "description": "Additional context about when/where this preference applies",
                },
            },
            "required": ["key", "value"],
        },
        handler=learn_preference_handler,
        requires_permission="write",
    )

    # Get Knowledge Stats
    register_tool(
        name="get_knowledge_stats",
        category="knowledge",
        description="Get statistics about A.R.C.H.I.E.'s knowledge base including counts by type, top categories, and growth trends.",
        input_schema={"type": "object", "properties": {}},
        handler=get_knowledge_stats_handler,
        requires_permission="read",
    )

    # GitHub Repository Tools
    register_tool(
        name="github_list_repos",
        category="knowledge",
        description="List all tracked GitHub repositories with file counts, indexing status, and stats breakdown (code/docs/config).",
        input_schema={"type": "object", "properties": {}},
        handler=github_list_repos_handler,
        requires_permission="read",
    )

    register_tool(
        name="github_index_repo",
        category="knowledge",
        description="Index a GitHub repository into ARCHIE's knowledge base. Indexes all code, docs, and config files up to 2000 per repo (configurable).",
        input_schema={
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "GitHub repository URL (e.g., https://github.com/owner/repo)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Indexing priority (affects importance score). Default: high",
                    "default": "high",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Max files to index (10-10000). Overrides per-repo cap. Default: 2000",
                },
            },
            "required": ["repo_url"],
        },
        handler=github_index_repo_handler,
        requires_permission="write",
    )

    register_tool(
        name="github_search",
        category="knowledge",
        description="Search across indexed GitHub files using semantic similarity or text matching. Find code, docs, or config files by meaning.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - matched semantically against indexed GitHub files",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10, max: 50)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=github_search_handler,
        requires_permission="read",
    )

    logger.info(
        "Registered 9 knowledge tools: search_knowledge, store_memory, get_user_preferences, recall_context, learn_preference, get_knowledge_stats, github_list_repos, github_index_repo, github_search"
    )


# Auto-register when module is imported
register_knowledge_tools()
