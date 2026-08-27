"""
A.R.C.H.I.E. Memory Manager
Handles long-term memory storage, recall, and learning
"""

import os
from database import _get_db_password
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# MEMORY EXTRACTION
# ============================================================================


def extract_memories_from_conversation(user_message, ai_response, user_id=None):
    """
    Extract important information from a conversation to store as memories

    Returns: List of memory objects to store
    """
    memories = []

    # Extract website/company information
    website_info = extract_website_info(user_message, ai_response)
    if website_info:
        memories.extend(website_info)

    # Extract user preferences
    preferences = extract_preferences(user_message, ai_response)
    if preferences:
        memories.extend(preferences)

    # Extract factual information
    facts = extract_facts(user_message, ai_response)
    if facts:
        memories.extend(facts)

    # Extract procedures/solutions
    procedures = extract_procedures(user_message, ai_response)
    if procedures:
        memories.extend(procedures)

    # Extract technical details
    technical = extract_technical_details(user_message, ai_response)
    if technical:
        memories.extend(technical)

    # Add user_id to all memories
    if user_id:
        for memory in memories:
            memory["user_id"] = user_id

    return memories


def extract_website_info(user_msg, ai_msg):
    """Extract website/company information"""
    memories = []

    # Look for website details
    patterns = [
        r"(?:website|site|domain)(?:\s+is|\s*:|\s+at)?\s+([a-zA-Z0-9.-]+\.[a-z]{2,})",
        r"company(?:\s+name|\s+is|\s*:)?\s+([A-Z][a-zA-Z\s&]+)",
        r"business(?:\s+name|\s+is|\s*:)?\s+([A-Z][a-zA-Z\s&]+)",
    ]

    combined_text = user_msg + " " + ai_msg

    for pattern in patterns:
        matches = re.findall(pattern, combined_text, re.IGNORECASE)
        for match in matches:
            if len(match) > 2:  # Avoid false positives
                memories.append(
                    {
                        "memory_type": "company_info",
                        "category": "website",
                        "content": f"Website/Company: {match}",
                        "importance_score": 0.90,
                        "tags": ["website", "company", "business"],
                        "metadata": {"source": "conversation", "type": "website_info"},
                    }
                )

    return memories


def extract_preferences(user_msg, ai_msg):
    """Extract user preferences"""
    memories = []

    # Look for preference indicators
    preference_patterns = [
        r"(?:I|we) (?:prefer|like|want|need|use)\s+([a-zA-Z0-9\s]+)",
        r"(?:I|we) (?:always|usually|typically)\s+([a-zA-Z0-9\s]+)",
    ]

    for pattern in preference_patterns:
        matches = re.findall(pattern, user_msg, re.IGNORECASE)
        for match in matches:
            if 5 < len(match) < 100:
                memories.append(
                    {
                        "memory_type": "preference",
                        "category": "user_preference",
                        "content": f"User preference: {match}",
                        "importance_score": 0.75,
                        "tags": ["preference", "user_habit"],
                        "metadata": {"source": "conversation"},
                    }
                )

    return memories


def extract_facts(user_msg, ai_msg):
    """Extract factual statements"""
    memories = []

    # Look for definitive statements in AI response
    fact_patterns = [
        r"(?:is|are)\s+(?:a|an|the)\s+([a-zA-Z0-9\s]+)(?:that|which)",
        r"(?:means|refers to|indicates)\s+([a-zA-Z0-9\s]+)",
    ]

    for pattern in fact_patterns:
        matches = re.findall(pattern, ai_msg, re.IGNORECASE)
        for match in matches:
            if 10 < len(match) < 200:
                memories.append(
                    {
                        "memory_type": "fact",
                        "category": "knowledge",
                        "content": f"Fact: {match}",
                        "importance_score": 0.70,
                        "tags": ["fact", "knowledge"],
                        "metadata": {"source": "ai_response"},
                    }
                )

    return memories


def extract_procedures(user_msg, ai_msg):
    """Extract procedures and solutions"""
    memories = []

    # Look for step-by-step instructions
    if re.search(r"\b(?:step|first|then|next|finally)\b", ai_msg, re.IGNORECASE):
        # This is likely a procedure
        if len(ai_msg) > 50:
            memories.append(
                {
                    "memory_type": "procedure",
                    "category": "solution",
                    "content": f"Solution to: {user_msg[:100]}... | Response: {ai_msg[:500]}",
                    "importance_score": 0.85,
                    "tags": ["procedure", "solution", "how_to"],
                    "metadata": {
                        "source": "conversation",
                        "question": user_msg,
                        "solution": ai_msg,
                    },
                }
            )

    return memories


def extract_technical_details(user_msg, ai_msg):
    """Extract technical information"""
    memories = []

    # Look for code, configurations, or technical details
    if re.search(r"```|`[^`]+`|config|setup|install", ai_msg, re.IGNORECASE):
        # Extract code blocks
        code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", ai_msg, re.DOTALL)
        for code in code_blocks:
            if len(code) > 20:
                memories.append(
                    {
                        "memory_type": "technical",
                        "category": "code_snippet",
                        "content": f"Code for: {user_msg[:100]} | {code[:500]}",
                        "importance_score": 0.80,
                        "tags": ["code", "technical", "reference"],
                        "metadata": {
                            "source": "ai_response",
                            "context": user_msg,
                            "code": code,
                        },
                    }
                )

    return memories


# ============================================================================
# MEMORY STORAGE
# ============================================================================


def store_memory(memory_data):
    """
    Store a single memory in the database

    Args:
        memory_data: Dict with keys: user_id, memory_type, category, content,
                     importance_score, tags, metadata

    Returns: memory_id or None
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO long_term_memory
            (user_id, memory_type, category, content, importance_score, tags, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                memory_data.get("user_id"),
                memory_data.get("memory_type"),
                memory_data.get("category"),
                memory_data.get("content"),
                memory_data.get("importance_score", 0.5),
                memory_data.get("tags", []),
                json.dumps(memory_data.get("metadata", {})),
            ),
        )

        memory_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return memory_id

    except Exception as e:
        print(f"Error in store_memory: {e}")
        return None


def store_memories_batch(memories):
    """Store multiple memories at once"""
    stored_count = 0

    for memory in memories:
        if store_memory(memory):
            stored_count += 1

    return stored_count


# ============================================================================
# MEMORY RECALL
# ============================================================================


def recall_memories(query, user_id=None, memory_type=None, limit=10):
    """
    Search for relevant memories based on a query

    Args:
        query: Search string
        user_id: Optional user filter
        memory_type: Optional type filter (fact, procedure, preference, etc.)
        limit: Max results

    Returns: List of relevant memories
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build search query
        conditions = []
        params = []

        # Text search in content
        conditions.append("content ILIKE %s")
        params.append(f"%{query}%")

        # User filter
        if user_id:
            conditions.append("(user_id = %s OR user_id IS NULL)")
            params.append(user_id)

        # Type filter
        if memory_type:
            conditions.append("memory_type = %s")
            params.append(memory_type)

        where_clause = " AND ".join(conditions)
        params.append(limit)

        cur.execute(
            "SELECT *, EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400 as age_days "
            "FROM long_term_memory WHERE " + where_clause + " "
            "ORDER BY importance_score DESC, access_count DESC, created_at DESC LIMIT %s",
            params,
        )

        memories = cur.fetchall()

        # Update access count for recalled memories
        if memories:
            memory_ids = [m["id"] for m in memories]
            cur.execute(
                """
                UPDATE long_term_memory
                SET access_count = access_count + 1,
                    last_accessed = NOW()
                WHERE id = ANY(%s)
            """,
                (memory_ids,),
            )
            conn.commit()

        cur.close()
        conn.close()

        return [dict(m) for m in memories]

    except Exception as e:
        print(f"Error recalling memories: {e}")
        return []


def get_memory_context(user_message, user_id=None, max_context=5):
    """
    Get relevant memory context for a user message
    This is what A.R.C.H.I.E. "remembers" before responding

    Returns: String with remembered context
    """
    # Search for relevant memories
    memories = recall_memories(user_message, user_id=user_id, limit=max_context)

    if not memories:
        return None

    # Format as context
    context_parts = ["=== REMEMBERED CONTEXT ==="]

    for mem in memories:
        context_parts.append(f"[{mem['category']}] {mem['content']}")
        context_parts.append(f"  (Importance: {mem['importance_score']}, Accessed: {mem['access_count']} times)")

    context_parts.append("=== END CONTEXT ===")

    return "\n".join(context_parts)


# ============================================================================
# MEMORY MANAGEMENT
# ============================================================================


def get_memory_stats(user_id=None):
    """Get statistics about stored memories"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build user filter
        user_filter = ""
        params = []
        if user_id:
            user_filter = "WHERE user_id = %s OR user_id IS NULL"
            params = [user_id]

        # Total memories
        cur.execute(
            "SELECT COUNT(*) as total FROM long_term_memory " + user_filter,
            params,
        )
        total = cur.fetchone()["total"]

        # By type
        cur.execute(
            "SELECT memory_type, COUNT(*) as count FROM long_term_memory "
            + user_filter
            + " GROUP BY memory_type ORDER BY count DESC",
            params,
        )
        by_type = cur.fetchall()

        # By category
        cur.execute(
            "SELECT category, COUNT(*) as count FROM long_term_memory "
            + user_filter
            + " GROUP BY category ORDER BY count DESC",
            params,
        )
        by_category = cur.fetchall()

        # Most accessed
        cur.execute(
            "SELECT content, access_count, importance_score FROM long_term_memory "
            + user_filter
            + " ORDER BY access_count DESC LIMIT 10",
            params,
        )
        most_accessed = cur.fetchall()

        # Recent memories
        cur.execute(
            "SELECT content, memory_type, created_at FROM long_term_memory "
            + user_filter
            + " ORDER BY created_at DESC LIMIT 10",
            params,
        )
        recent = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "total_memories": total,
            "by_type": [dict(r) for r in by_type],
            "by_category": [dict(r) for r in by_category],
            "most_accessed": [dict(r) for r in most_accessed],
            "recent": [dict(r) for r in recent],
        }

    except Exception as e:
        print(f"Error getting memory stats: {e}")
        return None


def forget_old_memories(days=180, min_importance=0.3):
    """
    Archive or delete old, unimportant memories
    Keeps important ones forever
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM long_term_memory
            WHERE created_at < NOW() - INTERVAL '%s days'
              AND importance_score < %s
              AND access_count < 3
            RETURNING id
        """,
            (days, min_importance),
        )

        deleted_ids = cur.fetchall()
        conn.commit()
        cur.close()
        conn.close()

        return len(deleted_ids)

    except Exception as e:
        print(f"Error forgetting memories: {e}")
        return 0


# ============================================================================
# SMART MEMORY LEARNING
# ============================================================================


def learn_from_conversation(user_id, user_message, ai_response, conversation_metadata=None):
    """
    Main function to learn from a conversation
    Extracts and stores all important information

    Returns: Number of memories created
    """
    # Extract memories
    memories = extract_memories_from_conversation(user_message, ai_response, user_id)

    # Add conversation metadata to all memories
    if conversation_metadata:
        for memory in memories:
            if "metadata" not in memory:
                memory["metadata"] = {}
            memory["metadata"].update(conversation_metadata)

    # Store memories
    count = store_memories_batch(memories)

    return count
