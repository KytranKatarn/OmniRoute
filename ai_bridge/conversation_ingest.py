"""
A.R.C.H.I.E. Conversation Ingestion System
Receives conversations from ANY source (Ollama, Claude API, Claude Code CLI, etc.)
Processes with auto-tagging and emotional intelligence
Stores in consciousness database for learning and retrieval
"""

import sys
import json
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Dict, List, Optional

# Add to path for imports
sys.path.insert(0, "/app")
from ai_bridge.auto_tagger import (
    generate_tags_from_conversation,
    analyze_content,
    extract_code_snippets,
    summarize_conversation,
    should_store_knowledge,
)
from ai_bridge.emotional_intelligence import (
    analyze_sentiment,
    analyze_trust_impact,
    analyze_code_interaction,
)
from db import get_db


def ingest_conversation(
    user_message: str,
    ai_response: str,
    user_id: Optional[int] = None,
    source: str = "unknown",
    model: Optional[str] = None,
    provider: Optional[str] = None,
    environment: str = "production",
    metadata: Optional[Dict] = None,
) -> Dict[str, any]:
    """
    Ingest a conversation into A.R.C.H.I.E.'s consciousness

    Args:
        user_message: What the user said
        ai_response: What the AI responded
        user_id: Optional user ID
        source: Where this came from ('claude_code', 'ollama', 'api', 'chat', etc.)
        model: Model used (e.g., 'claude-sonnet-4', 'llama3.1:8b')
        provider: Provider ('anthropic', 'ollama', 'openai', etc.)
        environment: Environment context - 'production', 'sandbox_full', 'sandbox_<module>' (Phase 23)
        metadata: Additional metadata

    Returns:
        {
            'success': bool,
            'memory_id': int,
            'tags_applied': List[str],
            'sentiment': Dict,
            'trust_impact': Dict,
            'personality_update': Dict
        }
    """
    try:
        # 1. Check if worth storing
        if not should_store_knowledge(user_message, ai_response):
            return {
                "success": True,
                "skipped": True,
                "reason": "Not valuable enough to store",
            }

        # 2. Auto-tag the conversation
        tags = generate_tags_from_conversation(user_message, ai_response)

        # 3. Analyze content
        content_analysis = analyze_content(f"{user_message}\n{ai_response}")

        # 4. Analyze emotions and sentiment
        sentiment = analyze_sentiment(user_message)

        # 5. Analyze trust impact
        trust = analyze_trust_impact(user_message, ai_response)

        # 6. Analyze code interaction if applicable
        code_analysis = analyze_code_interaction(user_message, ai_response)

        # 7. Extract code snippets
        code_snippets = extract_code_snippets(ai_response)

        # 8. Generate summary
        summary = summarize_conversation(user_message, ai_response)

        # 9. Store in database
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Store in knowledge_base (unified schema - Phase 3)
            # Generate title from first 50 chars of user message
            title_text = user_message[:50].replace("\n", " ")
            if len(user_message) > 50:
                title_text += "..."

            cur.execute(
                """
                INSERT INTO knowledge_base
                (knowledge_type, title, content, category, tags, importance_score,
                 memory_metadata, source_type, source_id, created_at, updated_at, indexed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW())
                RETURNING id
            """,
                (
                    "conversation_memory",  # Fixed knowledge type
                    f"Conversation: {title_text}",  # Descriptive title
                    json.dumps(
                        {
                            "user_message": user_message,
                            "ai_response": ai_response,
                            "summary": summary,
                        }
                    ),
                    (content_analysis.get("tags", ["general"])[0] if content_analysis.get("tags") else "general"),
                    tags,
                    calculate_importance_score(sentiment, trust, content_analysis),
                    json.dumps(
                        {  # memory_metadata (renamed from metadata)
                            "source": source,
                            "model": model,
                            "provider": provider,
                            "environment": environment,  # Phase 23: Track sandbox vs production
                            "sentiment": sentiment,
                            "trust_impact": trust["trust_delta"],
                            "should_double_check": trust["should_double_check"],
                            "user_emotion": sentiment["user_emotion"],
                            "code_detected": content_analysis.get("code_detected", False),
                            "languages": content_analysis.get("languages", []),
                            "code_analysis": code_analysis,
                            "code_snippets_count": len(code_snippets),
                            "timestamp": datetime.now().isoformat(),
                            "user_id": user_id,  # Include user_id in metadata
                            **(metadata or {}),
                        }
                    ),
                    "conversation_ingest",  # source_type
                    f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{user_id or 0}",  # source_id (unique)
                ),
            )

            memory_id = cur.fetchone()["id"]

            # 10. Store code snippets separately if any
            for snippet in code_snippets:
                cur.execute(
                    """
                    INSERT INTO archie_codebase_knowledge
                    (knowledge_type, entity_name, file_path, description, code_snippet,
                     purpose, tags, metadata, auto_learned)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        "snippet",
                        f"Code from conversation #{memory_id}",
                        None,  # No specific file
                        summary,
                        snippet["code"],
                        f"Code example from conversation ({snippet['language']})",
                        tags,
                        json.dumps(
                            {
                                "language": snippet["language"],
                                "source": source,
                                "conversation_id": memory_id,
                                "quality_feedback": code_analysis["code_quality_feedback"],
                            }
                        ),
                        True,  # auto_learned
                    ),
                )

            # 11. Update user relationship and trust score
            if user_id:
                update_user_relationship(cur, user_id, sentiment, trust)

            # 12. Update A.R.C.H.I.E.'s personality traits
            personality_update = update_personality_traits(cur, sentiment, trust)

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
            "memory_id": memory_id,
            "tags_applied": tags,
            "sentiment": sentiment,
            "trust_impact": trust,
            "personality_update": personality_update,
            "code_snippets_stored": len(code_snippets),
            "importance_score": calculate_importance_score(sentiment, trust, content_analysis),
            "environment": environment,  # Phase 23: Track environment context
        }

    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def calculate_importance_score(sentiment: Dict, trust: Dict, content_analysis: Dict) -> float:
    """
    Calculate how important this conversation is (0-1.0)

    Higher scores for:
    - Positive feedback (builds confidence)
    - Negative feedback (learning opportunity)
    - Code examples
    - Technical content
    """
    score = 0.5  # Base score

    # Sentiment impact
    if sentiment["sentiment"] == "positive":
        score += 0.2
    elif sentiment["sentiment"] == "negative":
        score += 0.15  # Negative feedback is also valuable for learning!

    # Trust impact
    score += abs(trust["trust_delta"]) * 0.3

    # Code and technical content
    if content_analysis.get("code_detected"):
        score += 0.2

    if len(content_analysis.get("tags", [])) > 3:
        score += 0.1  # Rich technical content

    # Curiosity and learning
    if "curiosity" in sentiment.get("emotional_signals", []):
        score += 0.1

    return min(score, 1.0)


def update_user_relationship(cur, user_id: int, sentiment: Dict, trust: Dict):
    """
    Update relationship tracking with user

    Stores trust score, interaction style, personality fit
    """
    try:
        # Check if relationship exists
        cur.execute(
            """
            SELECT metadata FROM users WHERE id = %s
        """,
            (user_id,),
        )

        result = cur.fetchone()
        if not result:
            return

        metadata = result["metadata"] or {}

        # Initialize relationship tracking
        if "relationship" not in metadata:
            metadata["relationship"] = {
                "trust_score": 0.5,
                "total_interactions": 0,
                "positive_interactions": 0,
                "negative_interactions": 0,
                "interaction_style": "neutral",
                "last_sentiment": "neutral",
            }

        # Update relationship
        rel = metadata["relationship"]
        rel["total_interactions"] += 1
        rel["trust_score"] = max(0, min(1.0, rel["trust_score"] + trust["trust_delta"]))
        rel["last_sentiment"] = sentiment["sentiment"]

        if sentiment["sentiment"] == "positive":
            rel["positive_interactions"] += 1
        elif sentiment["sentiment"] == "negative":
            rel["negative_interactions"] += 1

        # Determine interaction style
        if rel["positive_interactions"] > rel["negative_interactions"] * 2:
            rel["interaction_style"] = "encouraging"
        elif rel["negative_interactions"] > rel["positive_interactions"] * 2:
            rel["interaction_style"] = "critical"
        else:
            rel["interaction_style"] = "balanced"

        # Update database
        cur.execute(
            """
            UPDATE users
            SET metadata = %s
            WHERE id = %s
        """,
            (json.dumps(metadata), user_id),
        )

    except Exception as e:
        print(f"Error updating user relationship: {e}")


def update_personality_traits(cur, sentiment: Dict, trust: Dict) -> Dict:
    """
    Update A.R.C.H.I.E.'s global personality traits based on interactions

    Stores in a special settings table
    """
    try:
        from ai_bridge.emotional_intelligence import generate_personality_traits

        # Get recent interaction history from knowledge_base (unified schema)
        cur.execute(
            """
            SELECT memory_metadata->>'sentiment' as sentiment,
                   (memory_metadata->>'trust_impact')::float as trust_delta,
                   memory_metadata->>'user_emotion' as user_emotion,
                   created_at
            FROM knowledge_base
            WHERE knowledge_type = 'conversation_memory'
            ORDER BY created_at DESC
            LIMIT 100
        """
        )

        history = []
        for row in cur.fetchall():
            if row["sentiment"]:
                history.append(
                    {
                        "sentiment": row["sentiment"],
                        "trust_delta": row["trust_delta"] or 0,
                        "user_emotion": row["user_emotion"] or "neutral",
                        "timestamp": row["created_at"],
                    }
                )

        # Generate personality traits
        personality = generate_personality_traits(history)

        # Store in system_config
        cur.execute(
            """
            SELECT id FROM system_config WHERE key = 'archie_personality'
        """
        )
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE system_config
                SET value = %s, updated_at = NOW()
                WHERE key = 'archie_personality'
            """,
                (json.dumps(personality),),
            )
        else:
            cur.execute(
                """
                INSERT INTO system_config (key, value, description, updated_at)
                VALUES ('archie_personality', %s, %s, NOW())
            """,
                (
                    json.dumps(personality),
                    "A.R.C.H.I.E. evolving personality traits based on user interactions",
                ),
            )

        return personality

    except Exception as e:
        print(f"Error updating personality traits: {e}")
        return {}


def retrieve_similar_conversations(
    query: str,
    user_id: Optional[int] = None,
    max_results: int = 5,
    min_importance: float = 0.3,
) -> List[Dict]:
    """
    Retrieve similar conversations from consciousness database
    This is the RAG (Retrieval-Augmented Generation) component

    Returns:
        List of similar conversations with context
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Generate tags for query
            query_analysis = analyze_content(query)
            query_tags = query_analysis.get("tags", [])

            # Search for conversations with overlapping tags (from knowledge_base)
            if query_tags:
                # Tag-based search
                cur.execute(
                    """
                    SELECT
                        id,
                        content,
                        category,
                        tags,
                        importance_score,
                        memory_metadata as metadata,
                        created_at
                    FROM knowledge_base
                    WHERE knowledge_type = 'conversation_memory'
                    AND tags && %s  -- Array overlap operator
                    AND importance_score >= %s
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT %s
                """,
                    (query_tags, min_importance, max_results),
                )
            else:
                # Fallback to recent important conversations
                cur.execute(
                    """
                    SELECT
                        id,
                        content,
                        category,
                        tags,
                        importance_score,
                        memory_metadata as metadata,
                        created_at
                    FROM knowledge_base
                    WHERE knowledge_type = 'conversation_memory'
                    AND importance_score >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """,
                    (min_importance, max_results),
                )

            results = cur.fetchall()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        # Format results
        conversations = []
        for row in results:
            content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
            conversations.append(
                {
                    "id": row["id"],
                    "user_message": content.get("user_message", ""),
                    "ai_response": content.get("ai_response", ""),
                    "summary": content.get("summary", ""),
                    "tags": row["tags"],
                    "importance": row["importance_score"],
                    "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                }
            )

        return conversations

    except Exception as e:
        print(f"Error retrieving conversations: {e}")
        return []


def get_archie_personality() -> Dict:
    """
    Get A.R.C.H.I.E.'s current personality traits

    Returns:
        Personality dict or default values
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT value FROM system_config
                WHERE key = 'archie_personality'
            """
            )

            result = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        if result and result["value"]:
            return json.loads(result["value"]) if isinstance(result["value"], str) else result["value"]

    except Exception as e:
        print(f"Error getting personality: {e}")

    # Default personality
    return {
        "confidence_level": 0.5,
        "cautiousness": 0.5,
        "enthusiasm": 0.6,
        "empathy": 0.6,
        "curiosity": 0.9,  # Always eager to learn!
        "personality_summary": "curious and eager to learn",
    }


# Example usage
if __name__ == "__main__":
    # Test ingestion
    result = ingest_conversation(
        user_message="How do I create a backup in PostgreSQL?",
        ai_response="You can use pg_dump to create a backup: pg_dump -U user -d database > backup.sql",
        user_id=1,
        source="test",
        model="test-model",
        provider="test",
    )
    print("Ingestion result:", json.dumps(result, indent=2))

    # Test retrieval
    similar = retrieve_similar_conversations("database backup")
    print(f"Found {len(similar)} similar conversations")
