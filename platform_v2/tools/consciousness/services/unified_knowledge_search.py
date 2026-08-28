"""
Unified Knowledge Search - A.R.C.H.I.E. Brain
Searches across all knowledge types with intelligent ranking

Search Priority:
1. mistake_learned (1.3x) - Prevent repeating errors!
2. vault_note (1.2x) - Curated documentation
3. code_snippet (1.1x) - Proven patterns
4. improvement (1.0x) - Historical changes
5. github_file (0.8x) - Indexed files
6. conversation_memory (0.8x) - Dynamic learning

Uses hybrid keyword (30%) + semantic (70%) search when embeddings available
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
from typing import List, Dict, Any


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def unified_knowledge_search(
    query: str,
    types: List[str] = None,
    category: str = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Search across all knowledge types with intelligent ranking

    Args:
        query: Search query string
        types: List of knowledge_types to search (default: all)
        category: Filter by category
        limit: Max results to return
        offset: Pagination offset

    Returns:
        {
            'results': [...],
            'total': count,
            'query': original_query,
            'types_searched': [...]
        }
    """

    if types is None:
        types = [
            "vault_note",
            "conversation_memory",
            "code_snippet",
            "github_file",
            "improvement",
            "mistake_learned",
        ]

    # Type-based importance multipliers
    # Priority order for knowledge retrieval
    type_weights = {
        "mistake_learned": 1.3,  # HIGHEST - prevent repeating mistakes!
        "vault_note": 1.2,  # HIGH - curated docs
        "github_file_selective": 1.1,  # NEW - manually indexed with embeddings
        "code_snippet": 1.1,  # ABOVE NORMAL - proven patterns
        "improvement": 1.0,  # NORMAL - historical changes
        "conversation_memory": 0.9,  # SLIGHTLY BELOW - dynamic learning
        "github_file": 0.85,  # IMPROVED from 0.8 - auto-indexed files
    }

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build query with filters
        sql = """
            SELECT
                id,
                knowledge_type,
                title,
                content,
                category,
                tags,
                importance_score,
                access_count,
                created_at,
                updated_at,
                last_accessed,
                -- Calculate weighted score
                CASE
                    WHEN knowledge_type = 'mistake_learned' THEN importance_score * 1.3
                    WHEN knowledge_type = 'vault_note' THEN importance_score * 1.2
                    WHEN knowledge_type = 'code_snippet' THEN importance_score * 1.1
                    WHEN knowledge_type = 'improvement' THEN importance_score * 1.0
                    ELSE importance_score * 0.8
                END as weighted_score,
                -- Text match score
                CASE
                    WHEN title ILIKE %s THEN 2.0
                    WHEN content ILIKE %s THEN 1.0
                    ELSE 0.5
                END as text_score
            FROM knowledge_base
            WHERE knowledge_type = ANY(%s)
              AND (
                title ILIKE %s
                OR content ILIKE %s
                OR %s = ANY(tags)
              )
        """

        params = [
            f"%{query}%",  # title match check
            f"%{query}%",  # content match check
            types,
            f"%{query}%",  # title search
            f"%{query}%",  # content search
            query,  # exact tag match
        ]

        # Add category filter if specified
        if category:
            sql += " AND category = %s"
            params.append(category)

        # Order by combined score (recalculate inline since we can't reference computed columns)
        sql += """
            ORDER BY (
                (CASE
                    WHEN knowledge_type = 'mistake_learned' THEN importance_score * 1.3
                    WHEN knowledge_type = 'vault_note' THEN importance_score * 1.2
                    WHEN knowledge_type = 'code_snippet' THEN importance_score * 1.1
                    WHEN knowledge_type = 'improvement' THEN importance_score * 1.0
                    ELSE importance_score * 0.8
                END) *
                (CASE
                    WHEN title ILIKE %s THEN 2.0
                    WHEN content ILIKE %s THEN 1.0
                    ELSE 0.5
                END)
            ) DESC, created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([f"%{query}%", f"%{query}%", limit, offset])

        cur.execute(sql, params)
        results = cur.fetchall()

        # Get total count
        count_sql = """
            SELECT COUNT(*) as total
            FROM knowledge_base
            WHERE knowledge_type = ANY(%s)
              AND (
                title ILIKE %s
                OR content ILIKE %s
                OR %s = ANY(tags)
              )
        """
        count_params = [types, f"%{query}%", f"%{query}%", query]

        if category:
            count_sql += " AND category = %s"
            count_params.append(category)

        cur.execute(count_sql, count_params)
        total = cur.fetchone()["total"]

        return {
            "results": results,
            "total": total,
            "query": query,
            "types_searched": types,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_knowledge_stats() -> Dict[str, Any]:
    """Get statistics about knowledge base"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Knowledge type distribution
        cur.execute(
            """
            SELECT
                knowledge_type,
                COUNT(*) as count,
                ROUND(AVG(importance_score)::numeric, 2) as avg_importance
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY count DESC
        """
        )
        type_distribution = cur.fetchall()

        # Category distribution
        cur.execute(
            """
            SELECT
                category,
                COUNT(*) as count
            FROM knowledge_base
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
        """
        )
        category_distribution = cur.fetchall()

        # Recent additions
        cur.execute(
            """
            SELECT COUNT(*) as recent_count
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '7 days'
        """
        )
        recent_additions = cur.fetchone()["recent_count"]

        # Total entries
        cur.execute("SELECT COUNT(*) as total FROM knowledge_base")
        total_entries = cur.fetchone()["total"]

        # Mistake learnings (high priority!)
        cur.execute(
            """
            SELECT COUNT(*) as mistake_count
            FROM knowledge_base
            WHERE knowledge_type = 'mistake_learned'
        """
        )
        mistake_count = cur.fetchone()["mistake_count"]

        return {
            "type_distribution": type_distribution,
            "category_distribution": category_distribution,
            "recent_additions": recent_additions,
            "total_entries": total_entries,
            "mistake_count": mistake_count,
        }

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def search_by_category(category: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get all knowledge entries for a specific category"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                knowledge_type,
                title,
                content,
                category,
                tags,
                importance_score,
                created_at
            FROM knowledge_base
            WHERE category = %s
            ORDER BY importance_score DESC, created_at DESC
            LIMIT %s
        """,
            (category, limit),
        )

        results = cur.fetchall()
        return results

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_top_knowledge(knowledge_type: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get top knowledge entries by type (by importance)"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                knowledge_type,
                title,
                content,
                category,
                tags,
                importance_score,
                access_count,
                created_at
            FROM knowledge_base
            WHERE knowledge_type = %s
            ORDER BY importance_score DESC, access_count DESC, created_at DESC
            LIMIT %s
        """,
            (knowledge_type, limit),
        )

        results = cur.fetchall()
        return results

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_recent_knowledge(days: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
    """Get recently added knowledge entries"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                knowledge_type,
                title,
                content,
                category,
                tags,
                importance_score,
                created_at
            FROM knowledge_base
            WHERE created_at > NOW() - INTERVAL '1 day' * %s
            ORDER BY created_at DESC
            LIMIT %s
        """,
            (days, limit),
        )

        results = cur.fetchall()
        return results

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_mistake_learnings(limit: int = 20) -> List[Dict[str, Any]]:
    """Get all mistake learnings (prevent repetition!)"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                id,
                title,
                content,
                category,
                tags,
                importance_score,
                memory_metadata,
                created_at
            FROM knowledge_base
            WHERE knowledge_type = 'mistake_learned'
            ORDER BY importance_score DESC, created_at DESC
            LIMIT %s
        """,
            (limit,),
        )

        results = cur.fetchall()
        return results

    except Exception as e:
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
